/* Reads the text copied from the portal's "Xem thời khóa biểu" table and builds an .ics file.
   Pure functions, no network: everything stays in the browser. Also loadable from node for tests. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.UteTimetable = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // Period -> [start, end] in "HH:MM" (same table as src/schedule_parser.py).
  const PERIODS = {
    1: ['07:30', '08:15'], 2: ['08:15', '09:00'], 3: ['09:00', '09:45'], 4: ['10:00', '10:45'],
    5: ['10:45', '11:30'], 6: ['11:30', '12:15'], 7: ['12:45', '13:30'], 8: ['13:30', '14:15'],
    9: ['14:15', '15:00'], 10: ['15:15', '16:00'], 11: ['16:00', '16:45'], 12: ['16:45', '17:30'],
    13: ['18:00', '18:45'], 14: ['18:45', '19:30'], 15: ['19:30', '20:15'], 16: ['20:15', '21:00'],
  };
  const DAY_INDEX = { hai: 0, ba: 1, tu: 2, nam: 3, sau: 4, bay: 5 };
  const DAY_MS = 86400000;
  const DEFAULT_PERIODS = 4;

  const SESSION_RE = new RegExp(
    '(Th\\u1ee9\\s+(?:Hai|Ba|T\\u01b0|N\\u0103m|S\\u00e1u|B\\u1ea3y)|Ch\\u1ee7\\s+nh\\u1eadt)\\s+' +
    '(\\d{1,2})\\s*\\((\\d{1,2})g(\\d{2})\\)\\s+(\\S+)\\s+' +
    '(\\d{2})/(\\d{2})/(\\d{4})\\s*-+>\\s*(\\d{2})/(\\d{2})/(\\d{4})\\)?(.*)$', 'i');
  const COURSE_RE = /^\s*(\d+)\s+([A-Za-z]{2,}\d+[A-Za-z0-9]*)_(\w+)-(.+)$/;

  function fold(text) {
    const out = [];
    const enc = new TextEncoder();
    let line = '';
    let bytes = 0;
    for (const ch of text) {
      const n = enc.encode(ch).length;
      if (bytes + n > 74) { out.push(line); line = ' '; bytes = 1; }
      line += ch;
      bytes += n;
    }
    out.push(line);
    return out.join('\r\n');
  }

  function weekdayIndex(label) {
    if (/ch\S*\s+nh/i.test(label)) return 6;
    const word = label.trim().split(/\s+/).pop().normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
    return DAY_INDEX[word.replace('\u0111', 'd')];
  }

  function utc(y, m, d) { return Date.UTC(y, m - 1, d); }
  function iso(ms) { return new Date(ms).toISOString().slice(0, 10); }
  function dowOf(ms) { return (new Date(ms).getUTCDay() + 6) % 7; }

  function splitCourse(rest) {
    const email = (rest.match(/\(Email:\s*([^)\s]+)\s*\)/i) || [])[1] || '';
    const head = rest.replace(/\(Email:[^)]*\).*$/i, '').trim();
    const cut = head.lastIndexOf('-');
    if (cut < 0) return { name: head, teacher: '', email };
    return { name: head.slice(0, cut).trim(), teacher: head.slice(cut + 1).trim(), email };
  }

  function parseTimetable(raw) {
    const warnings = [];
    const courses = [];
    let current = null;
    const lines = String(raw || '').normalize('NFC').split(/\r?\n/);

    for (const line of lines) {
      if (!line.trim() || /^\s*STT\b/i.test(line)) continue;
      const head = line.match(COURSE_RE);
      if (head) {
        const parts = splitCourse(head[4]);
        const credits = parseInt((head[4].match(/\)\s+(\d+)(?:\s|$)/) || [])[1], 10);
        current = {
          code: head[2], group: head[3], name: parts.name, teacher: parts.teacher, email: parts.email,
          credits: Number.isNaN(credits) ? null : credits, sessions: [],
        };
        courses.push(current);
      }
      const m = line.match(SESSION_RE);
      if (!m || !current) continue;
      const dow = weekdayIndex(m[1]);
      if (dow === undefined) { warnings.push('Không đọc được thứ: ' + m[1]); continue; }
      const from = utc(+m[8], +m[7], +m[6]);
      const to = utc(+m[11], +m[10], +m[9]);
      const first = from + ((dow - dowOf(from) + 7) % 7) * DAY_MS;
      if (first > to) { warnings.push(current.name + ': khoảng tuần không chứa thứ này'); continue; }
      const extra = (m[12] || '').split('\t').map((s) => s.trim()).filter(Boolean);
      current.sessions.push({
        dow, period: +m[2], hour: +m[3], minute: +m[4], room: m[5],
        firstDate: iso(first), lastDate: iso(to), count: Math.floor((to - first) / (7 * DAY_MS)) + 1,
        place: extra.join(', '),
      });
    }
    for (const c of courses) {
      if (!c.sessions.length) warnings.push(c.name + ': chưa có lịch học (có thể là đồ án hoặc chưa xếp lịch)');
      c.periods = estimatePeriods(c);
    }
    return { courses: courses.filter((c) => c.sessions.length), warnings };
  }

  // The table only gives the start period; guess length from credits (15 periods per credit).
  function estimatePeriods(course) {
    const total = course.sessions.reduce((n, s) => n + s.count, 0);
    if (!course.credits || !total) return DEFAULT_PERIODS;
    return Math.min(6, Math.max(2, Math.ceil((course.credits * 15) / total)));
  }

  function endOf(session, periods) {
    const blockEnd = session.period <= 6 ? 6 : session.period <= 12 ? 12 : 16;
    const last = Math.min(session.period + periods - 1, blockEnd);
    const table = PERIODS[last];
    if (table) {
      const [h, m] = table[1].split(':').map(Number);
      return h * 60 + m;
    }
    return session.hour * 60 + session.minute + 45 * periods;
  }

  const pad = (n) => String(n).padStart(2, '0');
  const stamp = (date, minutes) => date.replace(/-/g, '') + 'T' + pad(Math.floor(minutes / 60)) + pad(minutes % 60) + '00';
  const esc = (s) => String(s).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n');

  function buildIcs(courses, now) {
    const stampNow = (now || new Date()).toISOString().replace(/[-:]/g, '').replace(/\.\d+/, '');
    const out = [
      'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//UTE-Calendar//Dan lich//VI', 'CALSCALE:GREGORIAN',
      'X-WR-CALNAME:UTE-Calendar', 'X-WR-TIMEZONE:Asia/Ho_Chi_Minh',
      'BEGIN:VTIMEZONE', 'TZID:Asia/Ho_Chi_Minh', 'BEGIN:STANDARD', 'DTSTART:19700101T000000',
      'TZOFFSETFROM:+0700', 'TZOFFSETTO:+0700', 'TZNAME:ICT', 'END:STANDARD', 'END:VTIMEZONE',
    ];
    for (const c of courses) {
      for (const s of c.sessions) {
        const start = s.hour * 60 + s.minute;
        const end = Math.max(endOf(s, c.periods), start + 45);
        const desc = ['Giảng viên: ' + (c.teacher || 'chưa rõ'), 'Mã lớp học phần: ' + c.code + '_' + c.group,
          'Bắt đầu tiết ' + s.period + ', khoảng ' + c.periods + ' tiết'].join('\n');
        out.push('BEGIN:VEVENT',
          'UID:' + c.code + '-' + c.group + '-' + s.dow + '-' + s.firstDate + '-' + s.period + '@ute-calendar',
          'DTSTAMP:' + stampNow,
          'DTSTART;TZID=Asia/Ho_Chi_Minh:' + stamp(s.firstDate, start),
          'DTEND;TZID=Asia/Ho_Chi_Minh:' + stamp(s.firstDate, end));
        if (s.count > 1) out.push('RRULE:FREQ=WEEKLY;COUNT=' + s.count);
        out.push('SUMMARY:' + esc(c.name),
          'LOCATION:' + esc([s.room, s.place].filter(Boolean).join(', ')),
          'DESCRIPTION:' + esc(desc),
          'BEGIN:VALARM', 'TRIGGER:-PT30M', 'ACTION:DISPLAY', 'DESCRIPTION:' + esc(c.name), 'END:VALARM',
          'END:VEVENT');
      }
    }
    out.push('END:VCALENDAR');
    return out.map(fold).join('\r\n') + '\r\n';
  }

  function clock(minutes) { return pad(Math.floor(minutes / 60)) + ':' + pad(minutes % 60); }

  return { parseTimetable, buildIcs, estimatePeriods, endOf, clock, PERIODS };
});
