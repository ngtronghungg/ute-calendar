/**
 * UTE-Calendar – Thử nghiệm: Google Apps Script có gọi được cổng HCMUTE không?
 * CHỈ ĐỌC lịch, KHÔNG ghi gì vào Google Calendar.
 *
 * Cách chạy:
 * 1. Vào https://script.google.com → New project → dán toàn bộ file này.
 * 2. Project Settings (bánh răng) → Script properties → Add:
 *      HCMUTE_USER = MSSV của bạn
 *      HCMUTE_PASS = mật khẩu cổng trường
 * 3. Chọn hàm testPortal → Run → cấp quyền (Advanced → Go to ... (unsafe) vì là script của chính bạn).
 * 4. Xem Execution log, gửi lại kết quả (log không in mật khẩu/token).
 * 5. Thử xong: xoá 2 Script properties ở bước 2.
 */

// Hàm mặc định của Apps Script: bấm Run là chạy luôn, không cần chọn tên hàm
function myFunction() {
  Logger.log('Bắt đầu chạy thử...');
  testPortal();
}

const BASE ='https://portalapi.hcmute.edu.vn/api/';
const HEADERS = {
  apiKey: 'utepscRBF0zT2Mqo6vMw69YMOH43IrB2RtXBS0EHit2kzvL2auxaFJBvw==',
  clientId: 'ute',
};

function testPortal() {
  const props = PropertiesService.getScriptProperties();
  const user = props.getProperty('HCMUTE_USER');
  const pass = props.getProperty('HCMUTE_PASS');
  if (!user || !pass) throw new Error('Chưa đặt HCMUTE_USER / HCMUTE_PASS trong Script properties');

  // 1. Đăng nhập
  const t0 = Date.now();
  const login = UrlFetchApp.fetch(BASE + 'authenticate/authpsc', {
    method: 'post',
    contentType: 'application/json',
    headers: HEADERS,
    payload: JSON.stringify({ username: user.trim(), password: pass.trim(), type: 0 }),
    muteHttpExceptions: true,
  });
  Logger.log('[1] Login HTTP %s (%s ms)', login.getResponseCode(), Date.now() - t0);
  if (login.getResponseCode() !== 200) {
    Logger.log('Body (300 ký tự đầu): %s', login.getContentText().slice(0, 300));
    return;
  }
  const session = JSON.parse(login.getContentText());
  const token = session.Token;
  Logger.log('    Có token: %s | Hết hạn: %s | Các field trả về: %s',
    !!token, session.Expire, Object.keys(session).join(', '));
  if (!token) return;

  const auth = Object.assign({ Authorization: 'Bearer ' + token }, HEADERS);
  const get = (path) => UrlFetchApp.fetch(BASE + path, { headers: auth, muteHttpExceptions: true });

  // 2. Năm học / học kỳ
  const ytRes = get('student/yearandterm');
  Logger.log('[2] yearandterm HTTP %s', ytRes.getResponseCode());
  if (ytRes.getResponseCode() !== 200) return;
  const yt = JSON.parse(ytRes.getContentText());
  const year = yt.CurrentYear || yt.NamHienTai;
  const term = yt.CurrentTerm || yt.HocKyHienTai;
  Logger.log('    Năm học: %s | Học kỳ: %s', year, term);

  // 3. Thời khoá biểu cả kỳ
  const sRes = get('student/DrawingStudentSchedule_Perior?namhoc=' + encodeURIComponent(year) +
                   '&hocky=' + encodeURIComponent(term));
  Logger.log('[3] TKB HTTP %s', sRes.getResponseCode());
  if (sRes.getResponseCode() === 200) {
    const s = JSON.parse(sRes.getContentText());
    const list = Array.isArray(s) ? s : (s.result || s.data || []);
    Logger.log('    Số dòng lịch: %s | Field mẫu: %s',
      Array.isArray(list) ? list.length : '?',
      Array.isArray(list) && list[0] ? Object.keys(list[0]).join(', ') : JSON.stringify(s).slice(0, 200));
  }

  // 4. Lịch thi
  const eRes = get('student/showexambytime');
  Logger.log('[4] Lịch thi HTTP %s', eRes.getResponseCode());
  if (eRes.getResponseCode() === 200) {
    const e = JSON.parse(eRes.getContentText());
    const list = Array.isArray(e) ? e : (e.result || []);
    Logger.log('    Số môn thi: %s', list.length);
  }

  Logger.log('✅ XONG – Apps Script gọi được cổng trường.');
}
