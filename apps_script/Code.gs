/**
 * UTE-Calendar - Lịch học tự cập nhật HCMUTE
 * Google Apps Script Master Controller (Code.gs)
 *
 * Chạy trực tiếp trong tài khoản Google của người dùng.
 * Mật khẩu chỉ lưu trong PropertiesService.getUserProperties() của chính người dùng.
 */

const API_BASE = "https://portalapi.hcmute.edu.vn/api/";
const API_KEY = "utepscRBF0zT2Mqo6vMw69YMOH43IrB2RtXBS0EHit2kzvL2auxaFJBvw==";
const CLIENT_ID = "ute";
const CALENDAR_NAME = "HCMUTE";
const MAX_OPS_PER_RUN = 120;
const APPS_SCRIPT_VERSION = "1.0.0"; // Giới hạn thao tác mỗi lần chạy để không vượt quá quota 6 phút

/**
 * Menu khởi tạo khi người dùng mở bảng tính.
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("UTE-Calendar")
    .addItem("Bật tự động cập nhật", "showEnableDialog")
    .addItem("Cập nhật ngay", "syncNowManual")
    .addItem("Xem tình trạng", "showStatusSheet")
    .addSeparator()
    .addItem("Tắt và xoá mật khẩu", "disableAndWipe")
    .addToUi();
}

/**
 * Mở hộp thoại nhập thông tin MSSV và mật khẩu.
 */
function showEnableDialog() {
  const html = HtmlService.createHtmlOutputFromFile("Dialog")
    .setWidth(380)
    .setHeight(320)
    .setTitle("Bật tự động cập nhật lịch học");
  SpreadsheetApp.getUi().showModalDialog(html, "UTE-Calendar");
}

/**
 * Gọi từ Dialog.html khi người dùng bấm Bật.
 * Xác thực với cổng trường, lưu thông tin vào UserProperties, tạo Calendar và Trigger.
 */
function enableAutoSync(mssv, password) {
  const cleanMssv = String(mssv || "").trim();
  const cleanPass = String(password || "").trim();

  if (!cleanMssv || !cleanPass) {
    return { success: false, message: "Vui lòng nhập đầy đủ MSSV và mật khẩu." };
  }

  // 1. Thử đăng nhập cổng trường NGAY LẬP TỨC
  let authData = null;
  try {
    authData = portalLogin(cleanMssv, cleanPass);
  } catch (e) {
    return { success: false, message: "MSSV hoặc mật khẩu chưa đúng" };
  }

  if (!authData || !authData.Token) {
    return { success: false, message: "MSSV hoặc mật khẩu chưa đúng" };
  }

  // 2. Lưu vào PropertiesService.getUserProperties() (KHÔNG dùng ScriptProperties)
  const userProps = PropertiesService.getUserProperties();
  userProps.setProperty("mssv", cleanMssv);
  userProps.setProperty("password", cleanPass);
  userProps.setProperty("portalToken", authData.Token);
  userProps.setProperty("portalExpire", authData.Expire || "");
  userProps.setProperty("studentName", authData.FullName || authData.Username || "Sinh viên");
  userProps.setProperty("consecutiveAuthFailures", "0");
  userProps.setProperty("consecutiveNetworkFailures", "0");

  // 3. Tạo hoặc lấy Calendar tên "HCMUTE"
  let calId = userProps.getProperty("calendarId");
  let cal = null;
  if (calId) {
    try { cal = CalendarApp.getCalendarById(calId); } catch (e) {}
  }
  if (!cal) {
    const existing = CalendarApp.getCalendarsByName(CALENDAR_NAME);
    if (existing && existing.length > 0) {
      cal = existing[0];
    } else {
      cal = CalendarApp.createCalendar(CALENDAR_NAME, {
        timeZone: "Asia/Ho_Chi_Minh"
      });
    }
    calId = cal.getId();
    userProps.setProperty("calendarId", calId);
  }

  // 4. Tạo trigger tick() chạy mỗi 30 phút (xoá trigger cũ trước)
  const triggers = ScriptApp.getProjectTriggers();
  for (let i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === "tick") {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }
  ScriptApp.newTrigger("tick")
    .timeBased()
    .everyMinutes(30)
    .create();

  // 5. Chạy đồng bộ lần đầu
  try {
    syncNow(true);
  } catch (e) {
    console.warn("Lỗi đồng bộ lần đầu:", e);
  }

  updateStatusSheet();
  return {
    success: true,
    message: "Đã bật. Lịch học của bạn đang được thêm vào Google Lịch."
  };
}

/**
 * Trigger chạy mỗi 30 phút.
 * Kiểm tra lock và nextDue để không gọi mạng nếu chưa đến hạn.
 */
function tick() {
  const lock = LockService.getUserLock();
  if (!lock.tryLock(15000)) return;

  try {
    const userProps = PropertiesService.getUserProperties();
    const mssv = userProps.getProperty("mssv");
    const password = userProps.getProperty("password");
    if (!mssv || !password) return;

    const now = new Date();
    const nextDueStr = userProps.getProperty("nextDue");
    const nextDue = nextDueStr ? parseInt(nextDueStr, 10) : 0;

    // Nếu chưa đến hạn thì thoát ngay (tiết kiệm quota, không gọi mạng)
    if (now.getTime() < nextDue) {
      return;
    }

    // Đã đến hạn: thực hiện đồng bộ
    let syncResult = null;
    let isError = false;
    try {
      syncResult = syncNow(false);
    } catch (e) {
      isError = true;
      console.warn("Lỗi khi chạy tick():", e);
    }

    // Tính toán nextDue mới bằng hàm thuần Logic.nextRunAfter
    const todayClasses = getTodayClassesFromProps(userProps);
    const hotWindows = getHotWindowsForDay(todayClasses);
    const hasClassesToday = todayClasses.length > 0;

    let netFails = parseInt(userProps.getProperty("consecutiveNetworkFailures") || "0", 10);
    if (isError || (syncResult && syncResult.networkError)) {
      netFails++;
    } else {
      netFails = 0;
    }
    userProps.setProperty("consecutiveNetworkFailures", String(netFails));

    const nextDueDt = nextRunAfter(now, hotWindows, hasClassesToday, isError, netFails);
    userProps.setProperty("nextDue", String(nextDueDt.getTime()));
    userProps.setProperty("nextDueFormatted", Utilities.formatDate(nextDueDt, "Asia/Ho_Chi_Minh", "dd/MM/yyyy HH:mm"));

    updateStatusSheet();
  } finally {
    lock.releaseLock();
  }
}

/**
 * Nút Cập nhật ngay từ menu UTE-Calendar.
 */
function syncNowManual() {
  const ui = SpreadsheetApp.getUi();
  const userProps = PropertiesService.getUserProperties();
  if (!userProps.getProperty("mssv") || !userProps.getProperty("password")) {
    ui.alert("Chưa bật tự động cập nhật", "Vui lòng chọn 'Bật tự động cập nhật' từ menu UTE-Calendar trước.", ui.ButtonSet.OK);
    return;
  }

  ui.alert("Đang cập nhật", "Lịch học đang được kiểm tra và cập nhật từ cổng trường. Bạn có thể tiếp tục công việc.", ui.ButtonSet.OK);
  try {
    const res = syncNow(true);
    updateStatusSheet();
    if (res && res.message) {
      ui.alert("Hoàn tất", res.message, ui.ButtonSet.OK);
    }
  } catch (e) {
    ui.alert("Lỗi cập nhật", "Không thể cập nhật từ trường: " + (e.message || e), ui.ButtonSet.OK);
  }
}

/**
 * Hàm đồng bộ cốt lõi.
 */
function syncNow(isForce) {
  const userProps = PropertiesService.getUserProperties();
  const mssv = userProps.getProperty("mssv");
  const password = userProps.getProperty("password");
  if (!mssv || !password) return { success: false, message: "Chưa cấu hình tài khoản." };

  // 1. Xác thực cổng trường
  let token = userProps.getProperty("portalToken");
  const expireStr = userProps.getProperty("portalExpire");
  let needLogin = !token;

  if (expireStr) {
    try {
      const expDate = new Date(expireStr);
      if (new Date().getTime() >= expDate.getTime() - 60000) {
        needLogin = true;
      }
    } catch (e) {
      needLogin = true;
    }
  }

  if (needLogin) {
    try {
      const auth = portalLogin(mssv, password);
      token = auth.Token;
      userProps.setProperty("portalToken", token);
      userProps.setProperty("portalExpire", auth.Expire || "");
      userProps.setProperty("consecutiveAuthFailures", "0");
    } catch (err) {
      // Đăng nhập thất bại
      let authFails = parseInt(userProps.getProperty("consecutiveAuthFailures") || "0", 10) + 1;
      userProps.setProperty("consecutiveAuthFailures", String(authFails));

      // Sai mật khẩu 2 lần liên tiếp -> tắt trigger, xoá mật khẩu, gửi email cảnh báo
      if (authFails >= 2) {
        disableAndWipeInternal();
        sendEmailNotification(
          "UTE-Calendar - Cần cập nhật mật khẩu",
          "Mật khẩu cổng trường có thể đã đổi. Hãy mở bảng tính và bật lại tự động cập nhật."
        );
      }
      return { success: false, networkError: false, message: "Sai thông tin đăng nhập cổng trường." };
    }
  }

  // 2. Lấy năm học & học kỳ hiện tại
  let namhoc = "", hocky = "";
  try {
    const yt = fetchJson("student/yearandterm", token);
    namhoc = yt.CurrentYear || yt.NamHienTai || "";
    hocky = yt.CurrentTerm || yt.HocKyHienTai || "";
  } catch (e) {
    console.warn("Lỗi lấy năm học:", e);
    return { success: false, networkError: true, message: "Lỗi kết nối năm học." };
  }

  if (!namhoc || !hocky) {
    // Năm học mặc định nếu không lấy được
    const nowY = new Date().getFullYear();
    namhoc = `${nowY}-${nowY + 1}`;
    hocky = "HK01";
  }

  // 3. Lấy thời khoá biểu cả kỳ và lịch thi
  let rawSchedule = null;
  let rawExams = [];
  try {
    rawSchedule = fetchJson(`student/DrawingStudentSchedule_Perior?namhoc=${namhoc}&hocky=${hocky}`, token);
  } catch (e) {
    return { success: false, networkError: true, message: "Lỗi kết nối thời khoá biểu." };
  }

  try {
    const exByTime = fetchJson("student/showexambytime", token);
    if (Array.isArray(exByTime)) rawExams = rawExams.concat(exByTime);
  } catch (e) {}

  try {
    const exByTerm = fetchJson(`student/exam?namhoc=${namhoc}&hocky=${hocky}`, token);
    if (Array.isArray(exByTerm)) rawExams = rawExams.concat(exByTerm);
  } catch (e) {}

  // 4. Chuyển đổi dữ liệu sang định dạng sự kiện chuẩn bằng Logic.gs
  const classEvents = parseSemesterSchedule(rawSchedule);
  const examEvents = parseExamSchedule(rawExams);
  const allEvents = classEvents.concat(examEvents);

  // Lưu các buổi học hôm nay vào UserProperties để hàm tick() tính hot window nhanh
  saveTodayClassesToProps(userProps, classEvents);

  // 5. Kiểm tra mã băm: nếu không đổi và không bắt buộc thì không đụng vào lịch
  const newHash = computeScheduleHash(allEvents);
  const storedHash = userProps.getProperty("eventHash");
  if (!isForce && storedHash && storedHash === newHash) {
    const nowTs = new Date().getTime();
    userProps.setProperty("lastSync", String(nowTs));
    userProps.setProperty("lastSyncFormatted", Utilities.formatDate(new Date(nowTs), "Asia/Ho_Chi_Minh", "dd/MM/yyyy HH:mm"));
    return { success: true, message: "Lịch học không có thay đổi mới.", changesCount: 0 };
  }

  // 6. Lấy Calendar và đồng bộ sự kiện
  const calId = userProps.getProperty("calendarId");
  const cal = CalendarApp.getCalendarById(calId);
  if (!cal) return { success: false, message: "Không tìm thấy lịch HCMUTE." };

  // Khoảng thời gian kiểm tra: từ hôm qua đến 120 ngày sau
  const startRange = new Date();
  startRange.setDate(startRange.getDate() - 1);
  startRange.setHours(0, 0, 0, 0);

  const endRange = new Date();
  endRange.setDate(endRange.getDate() + 120);
  endRange.setHours(23, 59, 59, 999);

  // Lấy các sự kiện hiện có trong Google Calendar
  const existingCalEvents = cal.getEvents(startRange, endRange);
  const existingMap = {};
  existingCalEvents.forEach(e => {
    const tagUid = e.getTag("uid");
    if (tagUid) {
      existingMap[tagUid] = {
        uid: tagUid,
        title: e.getTitle(),
        room: e.getLocation(),
        rawEvent: e
      };
    }
  });

  // Lọc các sự kiện từ trường nằm trong khoảng startRange -> endRange
  const relevantPortalEvents = allEvents.filter(ev => {
    const evD = new Date(ev.year || ev.startYear, (ev.month || ev.startMonth) - 1, ev.day || ev.startDay);
    return evD >= startRange && evD <= endRange;
  });

  // Tính sai khác (diff)
  const diff = diffEvents(Object.values(existingMap), relevantPortalEvents);

  // Quản lý màu môn học (lưu map trong UserProperties)
  let colorMap = {};
  try {
    colorMap = JSON.parse(userProps.getProperty("courseColorMap") || "{}");
  } catch (e) {
    colorMap = {};
  }

  let opsCount = 0;
  const changeLogs = [];

  // Thêm sự kiện mới
  for (let i = 0; i < diff.toAdd.length; i++) {
    if (opsCount >= MAX_OPS_PER_RUN) break;
    const item = diff.toAdd[i];

    const isClass = item.event_type === "CLASS";
    const startDt = new Date(
      item.year || item.startYear,
      (item.month || item.startMonth) - 1,
      item.day || item.startDay,
      item.startHour,
      item.startMin
    );
    const endDt = new Date(
      item.year || item.startYear,
      (item.month || item.startMonth) - 1,
      item.day || item.startDay,
      item.endHour,
      item.endMin
    );

    const newEv = cal.createEvent(item.title, startDt, endDt, {
      description: item.description,
      location: item.location
    });

    newEv.setTag("uid", item.uid);

    // Gán màu
    if (isClass) {
      const courseKey = item.subjectCode || item.subjectName;
      colorMap = assignCourseColor(courseKey, colorMap);
      const cId = colorMap[courseKey.toUpperCase()] || 9;
      try { newEv.setColor(String(cId)); } catch (e) {}

      // Nhắc nhở lớp học: trước 20 phút
      newEv.removeAllReminders();
      newEv.addPopupReminder(20);
    } else {
      // Lịch thi: luôn màu ĐỎ (11), nhắc trước 1 ngày và trước 2 giờ
      try { newEv.setColor(String(EXAM_COLOR)); } catch (e) {}
      newEv.removeAllReminders();
      newEv.addPopupReminder(1440); // 1 ngày
      newEv.addPopupReminder(120);  // 2 giờ
    }

    opsCount++;
  }

  // Cập nhật sự kiện có thay đổi phòng / giờ
  for (let i = 0; i < diff.toUpdate.length; i++) {
    if (opsCount >= MAX_OPS_PER_RUN) break;
    const item = diff.toUpdate[i];
    const ex = existingMap[item.uid];
    if (ex && ex.rawEvent) {
      if (item.newRoom) ex.rawEvent.setLocation(`Phòng ${item.newRoom}, HCMUTE`);
      if (item.newTitle) ex.rawEvent.setTitle(item.newTitle);
      changeLogs.push(`Cập nhật phòng học môn ${item.newTitle || item.uid} sang ${item.newRoom || ""}`);
    }
    opsCount++;
  }

  // Xoá sự kiện bị báo nghỉ
  for (let i = 0; i < diff.toDelete.length; i++) {
    if (opsCount >= MAX_OPS_PER_RUN) break;
    const item = diff.toDelete[i];
    if (item && item.rawEvent) {
      changeLogs.push(`Buổi ${item.title || "học"} đã được báo nghỉ hoặc huỷ`);
      item.rawEvent.deleteEvent();
    }
    opsCount++;
  }

  // Lưu map màu
  userProps.setProperty("courseColorMap", JSON.stringify(colorMap));
  userProps.setProperty("eventHash", newHash);

  const nowTs = new Date().getTime();
  userProps.setProperty("lastSync", String(nowTs));
  userProps.setProperty("lastSyncFormatted", Utilities.formatDate(new Date(nowTs), "Asia/Ho_Chi_Minh", "dd/MM/yyyy HH:mm"));

  // Đếm tổng số sự kiện trong lịch
  try {
    const totalCount = cal.getEvents(startRange, endRange).length;
    userProps.setProperty("calendarEventCount", String(totalCount));
  } catch (e) {}

  // Ghi nhật ký thay đổi và gửi email nếu có lịch bị nghỉ hoặc đổi phòng
  if (changeLogs.length > 0) {
    appendChangeLogs(userProps, changeLogs);
    sendEmailNotification(
      "UTE-Calendar - Lịch học có thay đổi",
      "Chào bạn,\n\nLịch học của bạn có thay đổi mới từ cổng trường:\n- " + changeLogs.join("\n- ") + "\n\nLịch trong Google Calendar của bạn đã được cập nhật tự động."
    );
  }

  // Nếu còn thao tác dở dang do chạm giới hạn quota, hẹn chạy tiếp sau 1 phút
  if (opsCount >= MAX_OPS_PER_RUN) {
    userProps.setProperty("nextDue", String(new Date().getTime() + 60 * 1000));
  }

  return {
    success: true,
    message: `Đã cập nhật xong lịch học (${diff.toAdd.length} thêm mới, ${diff.toUpdate.length} thay đổi, ${diff.toDelete.length} huỷ).`,
    changesCount: changeLogs.length
  };
}

/**
 * Hiển thị và cập nhật sheet "Tình trạng".
 */
function showStatusSheet() {
  updateStatusSheet();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName("Tình trạng");
  if (sheet) ss.setActiveSheet(sheet);
}

function updateStatusSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName("Tình trạng");
  if (!sheet) {
    sheet = ss.insertSheet("Tình trạng");
  }

  const userProps = PropertiesService.getUserProperties();
  const mssv = userProps.getProperty("mssv");
  const isEnabled = Boolean(mssv && userProps.getProperty("password"));
  const lastSyncStr = userProps.getProperty("lastSyncFormatted") || "Chưa có";
  const nextDueStr = userProps.getProperty("nextDueFormatted") || "Đang tính toán";
  const evCount = userProps.getProperty("calendarEventCount") || "0";

  let logs = [];
  try {
    logs = JSON.parse(userProps.getProperty("recentLogs") || "[]");
  } catch (e) {
    logs = [];
  }

  sheet.clear();
  sheet.setTabColor("#C0554A");

  // Thiết lập bảng thông tin
  sheet.getRange("A1:D1").merge().setValue("TÌNH TRẠNG TỰ ĐỘNG CẬP NHẬT LỊCH HỌC (UTE-Calendar)")
    .setFontWeight("bold").setFontSize(14).setBackground("#222120").setFontColor("#E6E1D8");

  const rows = [
    ["Trạng thái", isEnabled ? "Đang bật" : "Đã tắt", "Mã số sinh viên", mssv || "Chưa thiết lập"],
    ["Lần cập nhật gần nhất", lastSyncStr, "Lần cập nhật kế tiếp", nextDueStr],
    ["Số buổi trong lịch", evCount, "Lịch Google Calendar", CALENDAR_NAME]
  ];

  sheet.getRange(2, 1, rows.length, 4).setValues(rows);
  sheet.getRange("A2:A4").setFontWeight("bold").setFontColor("#A09A8E");
  sheet.getRange("C2:C4").setFontWeight("bold").setFontColor("#A09A8E");

  // Nhật ký 10 thay đổi gần nhất
  sheet.getRange("A6:D6").merge().setValue("10 THAY ĐỔI GẦN NHẤT")
    .setFontWeight("bold").setFontSize(12).setBackground("#222120").setFontColor("#E6E1D8");

  sheet.getRange("A7:D7").setValues([["Thời gian", "Nội dung thay đổi", "", ""]]).setFontWeight("bold");
  sheet.getRange("B7:D7").merge();

  if (logs.length === 0) {
    sheet.getRange("A8:D8").merge().setValue("Chưa ghi nhận thay đổi nào từ trường.").setFontStyle("italic").setFontColor("#77726A");
  } else {
    const logRows = logs.slice(0, 10).map(l => [l.time, l.message, "", ""]);
    sheet.getRange(8, 1, logRows.length, 4).setValues(logRows);
    for (let r = 8; r < 8 + logRows.length; r++) {
      sheet.getRange(r, 2, 1, 3).merge();
    }
  }

  sheet.autoResizeColumns(1, 4);
}

/**
 * Tắt và xoá mật khẩu: xoá trigger, xoá UserProperties, hỏi xác nhận trước.
 */
function disableAndWipe() {
  const ui = SpreadsheetApp.getUi();
  const resp = ui.alert(
    "Tắt và xoá mật khẩu",
    "Bạn có chắc muốn tắt tự động cập nhật và xoá toàn bộ thông tin đăng nhập khỏi tài khoản Google của bạn?",
    ui.ButtonSet.YES_NO
  );

  if (resp !== ui.Button.YES) return;

  disableAndWipeInternal();
  updateStatusSheet();
  ui.alert("Đã tắt", "Đã tắt tự động cập nhật và xoá mật khẩu khỏi tài khoản Google của bạn.", ui.ButtonSet.OK);
}

function disableAndWipeInternal() {
  // Xoá trigger tick
  const triggers = ScriptApp.getProjectTriggers();
  for (let i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === "tick") {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }

  // Xoá UserProperties
  PropertiesService.getUserProperties().deleteAllProperties();
}

/**
 * Đăng nhập cổng trường HCMUTE qua UrlFetchApp.
 */
function portalLogin(username, password) {
  const url = API_BASE + "authenticate/authpsc";
  const payload = {
    username: String(username).trim(),
    password: String(password).trim(),
    type: 0
  };

  const options = {
    method: "post",
    contentType: "application/json",
    headers: {
      apiKey: API_KEY,
      clientId: CLIENT_ID,
      "User-Agent": "UTE-Calendar-AppsScript/1.0"
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  const resp = UrlFetchApp.fetch(url, options);
  if (resp.getResponseCode() !== 200) {
    throw new Error("Đăng nhập thất bại: HTTP " + resp.getResponseCode());
  }

  return JSON.parse(resp.getContentText());
}

/**
 * Gọi API cổng trường HCMUTE có xác thực Bearer token.
 */
function fetchJson(endpoint, token) {
  const url = API_BASE + endpoint;
  const options = {
    method: "get",
    headers: {
      apiKey: API_KEY,
      clientId: CLIENT_ID,
      Authorization: "Bearer " + token,
      "User-Agent": "UTE-Calendar-AppsScript/1.0"
    },
    muteHttpExceptions: true
  };

  const resp = UrlFetchApp.fetch(url, options);
  const code = resp.getResponseCode();
  if (code === 401) {
    throw new Error("Phiên đăng nhập hết hạn (401).");
  }
  if (code !== 200) {
    throw new Error("Lỗi máy chủ trường (HTTP " + code + ")");
  }

  return JSON.parse(resp.getContentText());
}

/**
 * Lưu các buổi học của ngày hôm nay vào UserProperties.
 */
function saveTodayClassesToProps(userProps, events) {
  const today = new Date();
  const tYear = today.getFullYear();
  const tMonth = today.getMonth() + 1;
  const tDay = today.getDate();

  const todayClasses = (events || []).filter(e => {
    return e.year === tYear && e.month === tMonth && e.day === tDay;
  }).map(e => ({
    startHour: e.startHour,
    startMin: e.startMin,
    endHour: e.endHour,
    endMin: e.endMin
  }));

  userProps.setProperty("todayClassesJson", JSON.stringify(todayClasses));
}

function getTodayClassesFromProps(userProps) {
  try {
    return JSON.parse(userProps.getProperty("todayClassesJson") || "[]");
  } catch (e) {
    return [];
  }
}

/**
 * Ghi nhận nhật ký thay đổi (tối đa 10 dòng gần nhất).
 */
function appendChangeLogs(userProps, newChangeMsgs) {
  let logs = [];
  try {
    logs = JSON.parse(userProps.getProperty("recentLogs") || "[]");
  } catch (e) {
    logs = [];
  }

  const timeStr = Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "dd/MM/yyyy HH:mm");
  newChangeMsgs.forEach(msg => {
    logs.unshift({ time: timeStr, message: msg });
  });

  logs = logs.slice(0, 10);
  userProps.setProperty("recentLogs", JSON.stringify(logs));
}

/**
 * Gửi email thông báo đơn giản tới chủ tài khoản.
 */
function sendEmailNotification(subject, body) {
  try {
    const email = Session.getActiveUser().getEmail();
    if (email) {
      MailApp.sendEmail(email, subject, body);
    }
  } catch (e) {
    console.warn("Không thể gửi email thông báo:", e);
  }
}

/**
 * Kiểm tra phiên bản mới định kỳ từ server.
 */
function checkAppsScriptUpdate() {
  try {
    const url = "https://ute-calendar.com/apps_script_version.json";
    const res = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    if (res.getResponseCode() === 200) {
      const data = JSON.parse(res.getContentText());
      if (data && data.version) {
        if (compareVersions(APPS_SCRIPT_VERSION, data.version) < 0) {
          Logger.log("Có bản cập nhật mới cho UTE-Calendar: v" + data.version);
          return { hasUpdate: true, latest: data.version, message: data.message };
        }
      }
    }
  } catch (e) {
    // Bỏ qua lỗi kết nối
  }
  return { hasUpdate: false };
}
