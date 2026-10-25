(function () {
  const core = window.UteTimetable;
  const input = document.getElementById('pasteInput');
  const message = document.getElementById('pasteMessage');
  const result = document.getElementById('pasteResult');
  const list = document.getElementById('pasteCourses');
  const count = document.getElementById('pasteCount');
  const download = document.getElementById('pasteDownload');
  const apple = document.getElementById('pasteApple');
  const google = document.getElementById('pasteGoogle');
  const next = document.getElementById('pasteNext');
  const DAYS = ['Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy', 'Chủ nhật'];
  let courses = [];

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function showMessage(text) {
    message.textContent = text;
    message.classList.toggle('hidden', !text);
  }

  function sessionLine(course, s) {
    const start = s.hour * 60 + s.minute;
    const end = core.endOf(s, course.periods);
    const when = DAYS[s.dow] + ' ' + core.clock(start) + '-' + core.clock(end);
    const weeks = s.count > 1 ? s.count + ' tuần từ ' : '';
    const fmt = (d) => d.split('-').reverse().join('/');
    return when + ', phòng ' + s.room + ', ' + weeks + fmt(s.firstDate);
  }

  function renderCourse(course) {
    const row = el('div', 'paste-course');
    row.appendChild(el('div', 'paste-course-name', course.name));
    const meta = el('div', 'paste-course-meta');
    course.sessions.forEach((s) => meta.appendChild(el('div', '', sessionLine(course, s))));
    if (course.teacher) meta.appendChild(el('div', '', 'GV: ' + course.teacher));
    row.appendChild(meta);

    const label = el('label', 'paste-periods', 'Số tiết mỗi buổi');
    const field = el('input', 'input-control');
    field.type = 'number';
    field.min = '1';
    field.max = '6';
    field.value = String(course.periods);
    field.addEventListener('change', () => {
      const n = parseInt(field.value, 10);
      course.periods = Number.isNaN(n) ? course.periods : Math.min(6, Math.max(1, n));
      field.value = String(course.periods);
      meta.replaceChildren(...course.sessions.map((s) => el('div', '', sessionLine(course, s))));
      if (course.teacher) meta.appendChild(el('div', '', 'GV: ' + course.teacher));
    });
    label.appendChild(field);
    row.appendChild(label);
    return row;
  }

  function parseNow() {
    const text = input.value;
    list.replaceChildren();
    result.classList.add('hidden');
    if (!text.trim()) { showMessage(''); return; }
    const parsed = core.parseTimetable(text);
    courses = parsed.courses;
    if (!courses.length) {
      showMessage('Chưa đọc được môn nào. Hãy chọn đúng bảng "Xem thời khóa biểu" (có cột Tuần dạng 02/11/2026->28/12/2026) rồi Ctrl+A, Ctrl+C.');
      return;
    }
    showMessage(parsed.warnings.join(' | '));
    courses.forEach((c) => list.appendChild(renderCourse(c)));
    const events = courses.reduce((n, c) => n + c.sessions.reduce((m, s) => m + s.count, 0), 0);
    count.textContent = courses.length + ' môn, ' + events + ' buổi học';
    result.classList.remove('hidden');
  }

  input.addEventListener('input', parseNow);
  input.addEventListener('paste', () => setTimeout(parseNow, 0));

  function saveIcs() {
    const blob = new Blob([core.buildIcs(courses)], { type: 'text/calendar;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'ute-calendar-thoi-khoa-bieu.ics';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function showNext(text) {
    next.textContent = text;
    next.classList.remove('hidden');
  }

  // Neither calendar can be given a link to this timetable (nothing is uploaded), so both go through the file.
  apple.addEventListener('click', () => {
    saveIcs();
    showNext('Mở file vừa tải rồi bấm "Thêm tất cả". iPhone, iPad và Mac sẽ mở thẳng vào ứng dụng Lịch.');
  });

  google.addEventListener('click', () => {
    saveIcs();
    window.open('https://calendar.google.com/calendar/u/0/r/settings/export', '_blank', 'noopener');
    showNext('Ở trang Google Lịch vừa mở, bấm "Nhập", chọn file vừa tải rồi bấm "Nhập". Trên Android, bạn chỉ cần mở file .ics bằng ứng dụng Google Lịch.');
  });

  download.addEventListener('click', () => {
    saveIcs();
    showNext('Đã tải file. Mở file này bằng ứng dụng Lịch bạn đang dùng.');
  });
})();
