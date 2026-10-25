
/**
 * So sánh hai chuỗi semantic version (ví dụ "1.0.0" và "1.1.0").
 * Trả về: -1 nếu v1 < v2, 0 nếu v1 == v2, 1 nếu v1 > v2.
 */
function compareVersions(v1, v2) {
  const p1 = String(v1 || "0").split(".").map(n => parseInt(n, 10) || 0);
  const p2 = String(v2 || "0").split(".").map(n => parseInt(n, 10) || 0);
  const len = Math.max(p1.length, p2.length);
  for (let i = 0; i < len; i++) {
    const a = p1[i] || 0;
    const b = p2[i] || 0;
    if (a > b) return 1;
    if (a < b) return -1;
  }
  return 0;
}

/**
 * Kiểm tra cấu trúc dữ liệu trả về từ cổng trường trước khi phân tích.
 * Ngăn ngừa lỗi khi cổng trường đổi định dạng hoặc trả về dữ liệu hỏng.
 */
function validatePortalPayload(raw) {
  if (raw == null) return { ok: true, items: [] };
  let items = [];
  if (typeof raw === "object") {
    if (Array.isArray(raw.result)) items = raw.result;
    else if (Array.isArray(raw.data)) items = raw.data;
    else if (Array.isArray(raw)) items = raw;
    else {
      for (const k in raw) {
        if (Array.isArray(raw[k])) {
          items = raw[k];
          break;
        }
      }
    }
  } else {
    return { ok: false, error: "Dữ liệu cổng trường không phải đối tượng hoặc mảng" };
  }

  if (items.length === 0) return { ok: true, items: [] };

  const knownCourseKeys = ["tenhp", "tenhocphan", "subjectname", "subject", "classcoursename", "curriculumname", "tenmonhoc"];
  const knownDayKeys = ["thu", "dayofweek"];
  const knownPeriodKeys = ["periodid", "tiet", "tiethoc", "cahoc"];

  let readable = 0;
  for (const it of items) {
    if (!it || typeof it !== "object") continue;
    const keys = Object.keys(it).map(k => k.toLowerCase());
    const hasCourse = knownCourseKeys.some(k => keys.includes(k));
    const hasDay = knownDayKeys.some(k => keys.includes(k));
    const hasPeriod = knownPeriodKeys.some(k => keys.includes(k));
    if (hasCourse && hasDay && hasPeriod) readable++;
  }

  if (readable === 0 || readable / items.length < 0.5) {
    return { ok: false, error: "Định dạng thời khoá biểu không nhận dạng được (" + readable + "/" + items.length + ")" };
  }

  return { ok: true, items: items };
}
/**
 * UTE-Calendar - Pure Business Logic for Apps Script
 * Contains pure functions with ZERO Google service calls.
 * Runs in Google Apps Script and can be imported directly in Node.js for unit testing.
 */

// 1. Period time table (Khung giờ giảng dạy chính thức HCMUTE)
const PERIOD_TABLE = {
  1:  { startHour: 7,  startMin: 30, endHour: 8,  endMin: 15 },
  2:  { startHour: 8,  startMin: 15, endHour: 9,  endMin: 0  },
  3:  { startHour: 9,  startMin: 0,  endHour: 9,  endMin: 45 },
  4:  { startHour: 10, startMin: 0,  endHour: 10, endMin: 45 },
  5:  { startHour: 10, startMin: 45, endHour: 11, endMin: 30 },
  6:  { startHour: 11, startMin: 30, endHour: 12, endMin: 15 },
  7:  { startHour: 12, startMin: 45, endHour: 13, endMin: 30 },
  8:  { startHour: 13, startMin: 30, endHour: 14, endMin: 15 },
  9:  { startHour: 14, startMin: 15, endHour: 15, endMin: 0  },
  10: { startHour: 15, startMin: 15, endHour: 16, endMin: 0  },
  11: { startHour: 16, startMin: 0,  endHour: 16, endMin: 45 },
  12: { startHour: 16, startMin: 45, endHour: 17, endMin: 30 },
  13: { startHour: 18, startMin: 0,  endHour: 18, endMin: 45 },
  14: { startHour: 18, startMin: 45, endHour: 19, endMin: 30 },
  15: { startHour: 19, startMin: 30, endHour: 20, endMin: 15 },
  16: { startHour: 20, startMin: 15, endHour: 21, endMin: 0  }
};

// 2. Constants for Hot Window & Timing
const HOT_LEAD_MIN = 90;            // Start hot window 90m before class
const HOT_END_MIN = 10;             // End hot window 10m before class
const HOT_FLOOR_HOUR = 5;           // Floor hot window at 05:00
const QUIET_START_HOUR = 23;        // No scans 23:00 - 05:00
const QUIET_END_HOUR = 5;
const HOT_INTERVAL_MIN = 30;        // Inside hot window: 30-45 mins
const HOT_INTERVAL_MAX = 45;
const IDLE_INTERVAL_MIN = 120;      // Outside hot window: 120-240 mins
const IDLE_INTERVAL_MAX = 240;
const NO_CLASS_INTERVAL_MIN = 180;  // Day without classes: 180-240 mins
const NO_CLASS_INTERVAL_MAX = 240;
const JITTER_MAX_MIN = 2;           // Jitter ±2m

// 3. Google Calendar EventColor Palette (10 distinct colors for courses)
// 9: Blueberry, 6: Tangerine, 10: Basil, 3: Grape, 5: Banana,
// 7: Peacock, 4: Flamingo, 2: Sage, 1: Lavender, 8: Graphite
const COLOR_PALETTE = [9, 6, 10, 3, 5, 7, 4, 2, 1, 8];
const EXAM_COLOR = 11; // Tomato (Red)

// Day of week mapping
const DAY_MAP = {
  'thứ hai': 0, 'thứ 2': 0, 'monday': 0, 'mon': 0, '2': 0,
  'thứ ba': 1, 'thứ 3': 1, 'tuesday': 1, 'tue': 1, '3': 1,
  'thứ tư': 2, 'thứ 4': 2, 'wednesday': 2, 'wed': 2, '4': 2,
  'thứ năm': 3, 'thứ 5': 3, 'thursday': 3, 'thu': 3, '5': 3,
  'thứ sáu': 4, 'thứ 6': 4, 'friday': 4, 'fri': 4, '6': 4,
  'thứ bảy': 5, 'thứ 7': 5, 'saturday': 5, 'sat': 5, '7': 5,
  'chủ nhật': 6, 'cn': 6, 'sunday': 6, 'sun': 6, '8': 6
};


/**
 * Get period start and end time.
 */
function getPeriodTime(startP, endP) {
  const sp = Math.max(1, Math.min(parseInt(startP, 10) || 1, 16));
  const ep = Math.max(sp, Math.min(parseInt(endP, 10) || sp, 16));
  const s = PERIOD_TABLE[sp] || PERIOD_TABLE[1];
  const e = PERIOD_TABLE[ep] || PERIOD_TABLE[ep] || s;
  return {
    startHour: s.startHour,
    startMin: s.startMin,
    endHour: e.endHour,
    endMin: e.endMin
  };
}

/**
 * Parse string like "1-3", "Tiết 7-9", 10 into start and end periods.
 */
function parsePeriodRange(periodStr) {
  if (periodStr == null) return { startP: 1, endP: 3 };
  const s = String(periodStr).trim();
  const digits = (s.match(/\b\d+\b/g) || []).map(Number);
  if (!digits.length) return { startP: 1, endP: 3 };
  if (digits.length === 1) return { startP: digits[0], endP: digits[0] };
  return { startP: Math.min(...digits), endP: Math.max(...digits) };
}

/**
 * Parse date string DD/MM/YYYY or YYYY-MM-DD safely into { year, month, day }.
 */
function parseDate(dateStr) {
  if (!dateStr) return null;
  const s = String(dateStr).trim();
  const mDmy = s.match(/^(\d{1,2})[/-](\d{1,2})[/-](\d{4})/);
  if (mDmy) {
    return {
      year: parseInt(mDmy[3], 10),
      month: parseInt(mDmy[2], 10),
      day: parseInt(mDmy[1], 10)
    };
  }
  const mYmd = s.match(/^(\d{4})[/-](\d{1,2})[/-](\d{1,2})/);
  if (mYmd) {
    return {
      year: parseInt(mYmd[1], 10),
      month: parseInt(mYmd[2], 10),
      day: parseInt(mYmd[3], 10)
    };
  }
  return null;
}

/**
 * Format { year, month, day } to YYYYMMDD string.
 */
function toDateKey(d) {
  const y = String(d.year);
  const m = String(d.month).padStart(2, '0');
  const day = String(d.day).padStart(2, '0');
  return `${y}${m}${day}`;
}

/**
 * Check if a date object is between two date objects (inclusive).
 */
function dateCompare(a, b) {
  if (a.year !== b.year) return a.year - b.year;
  if (a.month !== b.month) return a.month - b.month;
  return a.day - b.day;
}

/**
 * Add days to { year, month, day }.
 */
function addDays(d, days) {
  const jsDate = new Date(Date.UTC(d.year, d.month - 1, d.day + days));
  return {
    year: jsDate.getUTCFullYear(),
    month: jsDate.getUTCMonth() + 1,
    day: jsDate.getUTCDate()
  };
}

/**
 * Get weekday (0 = Monday, ..., 6 = Sunday) for a { year, month, day }.
 */
function getWeekday(d) {
  const jsDate = new Date(Date.UTC(d.year, d.month - 1, d.day));
  const w = jsDate.getUTCDay(); // 0 is Sun, 1 is Mon...
  return (w + 6) % 7; // Convert to 0 = Mon, 6 = Sun
}

/**
 * Parse semester schedule from portal into individual class sessions.
 */
function parseSemesterSchedule(data) {
  let items = [];
  if (data && typeof data === 'object') {
    if (Array.isArray(data.result)) items = data.result;
    else if (Array.isArray(data.data)) items = data.data;
    else if (Array.isArray(data)) items = data;
    else {
      for (const k in data) {
        if (Array.isArray(data[k])) {
          items = data[k];
          break;
        }
      }
    }
  }

  const events = [];

  items.forEach((item, idx) => {
    if (!item || typeof item !== 'object') return;

    // Skip unassigned classes
    const xepTkb = String(item.XepTKB || '').trim().toLowerCase();
    if (xepTkb.includes('chưa xếp') || xepTkb.includes('không xếp')) return;

    const subjectName = (item.TenHP || item.ClassCourseName || item.CurriculumName || item.TenMonHoc || 'Môn học').trim();
    const subjectCode = (item.MaLHP || item.ClassCourseID || item.CurriculumID || item.MaHP || '').trim();
    const lecturer = (item.HoTenGV || item.ProfessorName || item.GiangVien || 'Chưa cập nhật').trim();
    const room = (item.Phong || item.Classroom || item.RoomID || 'Chưa xếp phòng').trim();
    const campus = (item.CampusName || 'HCMUTE').trim();

    // Target weekday (0 = Monday ... 6 = Sunday)
    let targetWeekday = null;
    const rawThu = String(item.Thu || '').trim().toLowerCase();
    if (rawThu in DAY_MAP) {
      targetWeekday = DAY_MAP[rawThu];
    } else if (item.DayOfWeek != null) {
      // HCMUTE: 1=Mon, 2=Tue...
      targetWeekday = parseInt(item.DayOfWeek, 10) - 1;
    }
    if (targetWeekday == null || isNaN(targetWeekday)) targetWeekday = 0;

    // Periods
    let startP = 1, endP = 3;
    if (item.PeriodID) {
      startP = parseInt(item.PeriodID, 10) || 1;
      const numP = parseInt(item.NumberOfPeriods, 10) || 3;
      endP = startP + numP - 1;
    } else {
      const p = parsePeriodRange(item.CaHoc || item.Tiet || item.TietHoc);
      startP = p.startP;
      endP = p.endP;
    }
    const pt = getPeriodTime(startP, endP);

    // Dates from TuanHoc or BeginDate/EndDate
    let beginD = null, endD = null;
    const tuanRaw = String(item.TuanHoc || item.WeekSchedule || '');
    const mRange = tuanRaw.match(/(\d{1,2}\/\d{1,2}\/\d{4})\s*->\s*(\d{1,2}\/\d{1,2}\/\d{4})/);
    if (mRange) {
      beginD = parseDate(mRange[1]);
      endD = parseDate(mRange[2]);
    }
    if (!beginD) {
      beginD = parseDate(item.BeginDate || item.TuNgay || item.TimeBeginDate);
    }
    if (!endD) {
      endD = parseDate(item.EndDate || item.DenNgay);
    }

    if (!beginD) return;
    if (!endD) {
      endD = addDays(beginD, 15 * 7);
    }

    // Generate weekly recurring dates
    let currD = beginD;
    const daysAhead = (targetWeekday - getWeekday(currD) + 7) % 7;
    currD = addDays(currD, daysAhead);

    while (dateCompare(currD, endD) <= 0) {
      const dateKey = toDateKey(currD);
      const codeOrIdx = subjectCode || `idx${idx}`;
      const uid = `hcmute-class-${codeOrIdx}-${dateKey}-p${startP}`;
      const titlePrefix = subjectCode ? `[${subjectCode}] ` : '';
      const title = `${titlePrefix}${subjectName}`;

      const desc = [
        `Môn học: ${subjectName}`,
        `Mã LHP: ${subjectCode}`,
        `Giảng viên: ${lecturer}`,
        `Tiết học: Tiết ${startP} - ${endP} (${String(pt.startHour).padStart(2, '0')}:${String(pt.startMin).padStart(2, '0')} - ${String(pt.endHour).padStart(2, '0')}:${String(pt.endMin).padStart(2, '0')})`,
        `Phòng: ${room}`,
        `Cơ sở: ${campus}`,
        `Hệ thống: online.hcmute.edu.vn`
      ].join('\n');

      const loc = `Phòng ${room}, Trường ĐH SPKT TP.HCM (${campus})`;

      events.push({
        uid: uid,
        title: title,
        subjectName: subjectName,
        subjectCode: subjectCode,
        lecturer: lecturer,
        room: room,
        campus: campus,
        location: loc,
        description: desc,
        event_type: 'CLASS',
        year: currD.year,
        month: currD.month,
        day: currD.day,
        startHour: pt.startHour,
        startMin: pt.startMin,
        endHour: pt.endHour,
        endMin: pt.endMin,
        startP: startP,
        endP: endP
      });

      currD = addDays(currD, 7);
    }
  });

  return events;
}

/**
 * Parse exam schedule into standardized events.
 */
function parseExamSchedule(examData) {
  let items = [];
  if (Array.isArray(examData)) items = examData;
  else if (examData && typeof examData === 'object') {
    if (Array.isArray(examData.result)) items = examData.result;
    else if (Array.isArray(examData.data)) items = examData.data;
  }

  const exams = [];
  const seen = new Set();

  items.forEach((item, idx) => {
    if (!item || typeof item !== 'object') return;
    const subject = (item.CurriculumName || item.TenHP || item.TenMonHoc || item.ClassCourseName || 'Thi môn học').trim();
    const code = (item.CurriculumID || item.MaHP || item.MaLHP || `exam_${idx}`).trim();
    const room = (item.PhongThi || item.Phong || 'Xem thông báo').trim();
    const location = (item.DiaDiem || 'HCMUTE').trim();
    const examType = (item.KyThi || 'Thi kết thúc học phần').trim();

    const examDateRaw = String(item.NgayThi || item.DateExam || '').trim();
    const examTimeRaw = String(item.GioThi || item.TimeExam || '07:30').trim();
    const durationMins = parseInt(item.ThoiLuong || item.ThoiGianLamBai || 90, 10) || 90;

    if (!examDateRaw || examDateRaw.toLowerCase() === 'null') return;
    const dateParsed = parseDate(examDateRaw);
    if (!dateParsed) return;

    let hh = 7, mm = 30;
    const mTime = examTimeRaw.match(/(\d{1,2})(?:g|h|:)(\d{2})/i);
    if (mTime) {
      hh = parseInt(mTime[1], 10);
      mm = parseInt(mTime[2], 10);
    }

    const dateKey = toDateKey(dateParsed);
    const timeKey = `${String(hh).padStart(2, '0')}${String(mm).padStart(2, '0')}`;
    const dedupKey = `${code}_${dateKey}_${timeKey}`;
    if (seen.has(dedupKey)) return;
    seen.add(dedupKey);

    const uid = `hcmute-exam-${code}-${dateKey}-${timeKey}`;
    const totalEndMins = hh * 60 + mm + durationMins;
    const endH = Math.floor(totalEndMins / 60) % 24;
    const endM = totalEndMins % 60;

    const title = `[LỊCH THI] ${subject}`;
    const desc = [
      `KỲ THI: ${examType}`,
      `Môn thi: ${subject}`,
      `Mã HP: ${code}`,
      `Phòng thi: ${room}`,
      `Thời gian làm bài: ${durationMins} phút`,
      `Địa điểm: ${location}`
    ].join('\n');

    exams.push({
      uid: uid,
      title: title,
      code: code,
      subject: subject,
      room: room,
      location: `Phòng thi ${room}, ${location}`,
      description: desc,
      event_type: 'EXAM',
      startYear: dateParsed.year,
      startMonth: dateParsed.month,
      startDay: dateParsed.day,
      startHour: hh,
      startMin: mm,
      endHour: endH,
      endMin: endM
    });
  });

  return exams;
}

/**
 * Calculate hot windows for a specific day based on the student's actual classes today.
 * Window: [earliest_slot_class - 90 min, earliest_slot_class - 10 min], floor 05:00.
 */
function getHotWindowsForDay(classesToday) {
  if (!classesToday || !classesToday.length) return [];

  // Group classes by slot: sáng (<12), chiều (12-17), tối (>=17)
  const slots = {
    sang: [],
    chieu: [],
    toi: []
  };

  classesToday.forEach(c => {
    if (c.startHour < 12) slots.sang.push(c);
    else if (c.startHour < 17) slots.chieu.push(c);
    else slots.toi.push(c);
  });

  const windows = [];

  ['sang', 'chieu', 'toi'].forEach(slotName => {
    const list = slots[slotName];
    if (!list.length) return;

    // Find earliest class in this slot
    list.sort((a, b) => (a.startHour * 60 + a.startMin) - (b.startHour * 60 + b.startMin));
    const firstClass = list[0];
    const classStartMins = firstClass.startHour * 60 + firstClass.startMin;

    // Window start: classStart - 90 min (floor at 05:00 = 300 min)
    let winStartMins = Math.max(HOT_FLOOR_HOUR * 60, classStartMins - HOT_LEAD_MIN);
    // Window end: classStart - 10 min
    let winEndMins = Math.max(winStartMins, classStartMins - HOT_END_MIN);

    windows.push({
      slot: slotName,
      startHour: Math.floor(winStartMins / 60),
      startMin: winStartMins % 60,
      endHour: Math.floor(winEndMins / 60),
      endMin: winEndMins % 60,
      classStartHour: firstClass.startHour,
      classStartMin: firstClass.startMin
    });
  });

  return windows;
}

/**
 * Determine the next run time after 'now' based on hot windows and scheduling rules.
 */
function nextRunAfter(now, hotWindows, hasClassesToday, isError, consecutiveErrors) {
  const currentMs = now.getTime();

  // If network error (429/5xx/timeout): retry after 30 min, max 3 times
  if (isError && (consecutiveErrors || 0) <= 3) {
    return new Date(currentMs + 30 * 60 * 1000);
  }

  const hour = now.getHours();
  const min = now.getMinutes();
  const nowMins = hour * 60 + min;

  // 1. Quiet hours: 23:00 to 05:00 -> scan tomorrow
  if (hour >= QUIET_START_HOUR || hour < QUIET_END_HOUR) {
    const nextDate = new Date(now);
    if (hour >= QUIET_START_HOUR) {
      nextDate.setDate(nextDate.getDate() + 1);
    }
    // Check if tomorrow has a morning hot window
    const morningWin = (hotWindows || []).find(w => w.startHour >= 5 && w.startHour <= 8);
    if (morningWin) {
      nextDate.setHours(morningWin.startHour, morningWin.startMin, 0, 0);
    } else {
      nextDate.setHours(6, 0, 0, 0); // Default 06:00
    }
    return nextDate;
  }

  // 2. Check if inside any hot window today
  const activeWindow = (hotWindows || []).find(w => {
    const wStart = w.startHour * 60 + w.startMin;
    const wEnd = w.endHour * 60 + w.endMin;
    return nowMins >= wStart && nowMins <= wEnd;
  });

  function randomBetween(minVal, maxVal) {
    return minVal + Math.floor(Math.random() * (maxVal - minVal + 1));
  }

  function getJitter() {
    return randomBetween(-JITTER_MAX_MIN, JITTER_MAX_MIN);
  }

  if (activeWindow) {
    // Inside hot window: next run 30-45 minutes later
    let interval = randomBetween(HOT_INTERVAL_MIN, HOT_INTERVAL_MAX) + getJitter();
    let nextRunMs = currentMs + interval * 60 * 1000;

    // Check if we need a final check 10-20 mins before class start
    if (activeWindow.classStartHour != null) {
      const classStartMs = new Date(now).setHours(activeWindow.classStartHour, activeWindow.classStartMin, 0, 0);
      const finalCheckMs = classStartMs - 15 * 60 * 1000;
      if (nextRunMs > finalCheckMs && currentMs < finalCheckMs) {
        nextRunMs = finalCheckMs;
      }
    }
    return new Date(nextRunMs);
  }

  // 3. Outside hot window
  // Check if there is an upcoming hot window today
  const upcomingWindow = (hotWindows || []).find(w => {
    const wStart = w.startHour * 60 + w.startMin;
    return nowMins < wStart;
  });

  let baseInterval;
  if (!hasClassesToday) {
    baseInterval = randomBetween(NO_CLASS_INTERVAL_MIN, NO_CLASS_INTERVAL_MAX) + getJitter();
  } else {
    baseInterval = randomBetween(IDLE_INTERVAL_MIN, IDLE_INTERVAL_MAX) + getJitter();
  }

  let targetMs = currentMs + baseInterval * 60 * 1000;

  if (upcomingWindow) {
    const upcomingStartMs = new Date(now).setHours(upcomingWindow.startHour, upcomingWindow.startMin, 0, 0);
    // Don't overshoot the start of the next hot window
    if (targetMs > upcomingStartMs) {
      targetMs = upcomingStartMs;
    }
  }

  // Don't schedule inside quiet hours (23:00-05:00)
  const targetDate = new Date(targetMs);
  if (targetDate.getHours() >= QUIET_START_HOUR) {
    const tomorrow = new Date(now);
    tomorrow.setDate(tomorrow.getDate() + 1);
    tomorrow.setHours(6, 0, 0, 0);
    return tomorrow;
  }

  return targetDate;
}

/**
 * Assign deterministic course color from 10-color palette.
 * Keeps existing assignments intact. Course 11 re-uses colors from index 0.
 */
function assignCourseColor(courseKey, existingMap) {
  const map = Object.assign({}, existingMap || {});
  const cleanKey = String(courseKey || '').trim().toUpperCase();
  if (!cleanKey) return map;

  if (cleanKey in map) return map;

  const usedCount = Object.keys(map).length;
  const colorIndex = usedCount % COLOR_PALETTE.length;
  map[cleanKey] = COLOR_PALETTE[colorIndex];
  return map;
}

/**
 * Compute deterministic hash of event list to skip unnecessary calendar mutations.
 */
function computeScheduleHash(events) {
  if (!events || !events.length) return 'empty_hash';
  const simplified = events.map(e => `${e.uid}|${e.title}|${e.room || ''}|${e.startIso || ''}`).sort().join(';;');

  // Simple, fast 32-bit FNV-1a hash implementation
  let hash = 0x811c9dc5;
  for (let i = 0; i < simplified.length; i++) {
    hash ^= simplified.charCodeAt(i);
    hash = (hash * 0x01000193) >>> 0;
  }
  return hash.toString(16);
}

/**
 * Compare calendar events with portal events to detect additions, updates, and cancellations.
 */
function diffEvents(existingInCalendar, newFromPortal) {
  const existingLen = (existingInCalendar || []).length;
  const newLen = (newFromPortal || []).length;

  // Mass deletion circuit breaker: If existing >= 5 and new < 30% of existing, abort deletion
  if (existingLen >= 5 && newLen < 0.3 * existingLen) {
    return {
      circuitBreakerTriggered: true,
      message: "Mass deletion circuit breaker triggered (existing=" + existingLen + ", new=" + newLen + ")",
      toAdd: [],
      toUpdate: [],
      toDelete: [],
    };
  }

  const existingMap = {};
  (existingInCalendar || []).forEach(e => {
    if (e && e.uid) existingMap[e.uid] = e;
  });

  const portalMap = {};
  (newFromPortal || []).forEach(e => {
    if (e && e.uid) portalMap[e.uid] = e;
  });

  const toAdd = [];
  const toUpdate = [];
  const toDelete = [];

  // Find additions and modifications
  for (const uid in portalMap) {
    const pEvent = portalMap[uid];
    if (!(uid in existingMap)) {
      toAdd.push(pEvent);
    } else {
      const ex = existingMap[uid];
      const roomChanged = (pEvent.room || '') !== (ex.room || '');
      const titleChanged = (pEvent.title || '') !== (ex.title || '');
      if (roomChanged || titleChanged) {
        toUpdate.push({
          uid: uid,
          oldEvent: ex,
          newEvent: pEvent,
          newRoom: pEvent.room,
          newTitle: pEvent.title
        });
      }
    }
  }

  // Find deletions / cancellations
  for (const uid in existingMap) {
    if (!(uid in portalMap)) {
      toDelete.push(existingMap[uid]);
    }
  }

  return { toAdd, toUpdate, toDelete };
}


// Export for Node.js unit testing
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    PERIOD_TABLE,
    HOT_LEAD_MIN,
    HOT_END_MIN,
    COLOR_PALETTE,
    EXAM_COLOR,
    getPeriodTime,
    parsePeriodRange,
    parseDate,
    parseSemesterSchedule,
    parseExamSchedule,
    getHotWindowsForDay,
    nextRunAfter,
    compareVersions,
    validatePortalPayload,
    assignCourseColor,
    computeScheduleHash,
    diffEvents
  };
}
