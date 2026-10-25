/**
 * Comprehensive Unit Tests for UTE-Calendar Apps Script Pure Logic (Logic.gs)
 * Run with: node apps_script/test_logic.js
 */

const assert = require('assert');
const Logic = require('./Logic.gs');

let testCount = 0;
let passCount = 0;

function runTest(name, fn) {
  testCount++;
  try {
    fn();
    passCount++;
    console.log(`  ✓ ${name}`);
  } catch (err) {
    console.error(`  ✗ ${name}`);
    console.error(`    ${err.message}`);
  }
}

console.log('Running UTE-Calendar Logic.gs Unit Tests...\n');

// 1. Period time conversion tests
console.log('1. Period Time Conversion (Tiết -> Giờ):');
runTest('Tiết 1 starts at 07:30 and ends at 08:15', () => {
  const t = Logic.getPeriodTime(1, 1);
  assert.strictEqual(t.startHour, 7);
  assert.strictEqual(t.startMin, 30);
  assert.strictEqual(t.endHour, 8);
  assert.strictEqual(t.endMin, 15);
});

runTest('Tiết 1-3 starts at 07:30 and ends at 09:45', () => {
  const t = Logic.getPeriodTime(1, 3);
  assert.strictEqual(t.startHour, 7);
  assert.strictEqual(t.startMin, 30);
  assert.strictEqual(t.endHour, 9);
  assert.strictEqual(t.endMin, 45);
});

runTest('Tiết 7-9 (ca chiều) starts at 12:45 and ends at 15:00', () => {
  const t = Logic.getPeriodTime(7, 9);
  assert.strictEqual(t.startHour, 12);
  assert.strictEqual(t.startMin, 45);
  assert.strictEqual(t.endHour, 15);
  assert.strictEqual(t.endMin, 0);
});

runTest('Tiết 13-15 (ca tối) starts at 18:00 and ends at 20:15', () => {
  const t = Logic.getPeriodTime(13, 15);
  assert.strictEqual(t.startHour, 18);
  assert.strictEqual(t.startMin, 0);
  assert.strictEqual(t.endHour, 20);
  assert.strictEqual(t.endMin, 15);
});

runTest('Parse period strings like "1-3", "Tiết 7-9", 10', () => {
  assert.deepStrictEqual(Logic.parsePeriodRange('1-3'), { startP: 1, endP: 3 });
  assert.deepStrictEqual(Logic.parsePeriodRange('Tiết 7-9'), { startP: 7, endP: 9 });
  assert.deepStrictEqual(Logic.parsePeriodRange('10'), { startP: 10, endP: 10 });
  assert.deepStrictEqual(Logic.parsePeriodRange(null), { startP: 1, endP: 3 });
});

// 2. Schedule Parsing & UID Generation
console.log('\n2. Schedule Parsing & UID Generation:');
runTest('parseSemesterSchedule converts raw portal JSON into recurring class sessions', () => {
  const rawData = {
    result: [
      {
        TenHP: 'Lập trình Web & Ứng dụng',
        MaLHP: 'COMP101',
        HoTenGV: 'TS. Nguyễn Văn A',
        Phong: 'A1-205',
        CampusName: 'Cơ sở chính',
        Thu: 'Thứ Hai',
        PeriodID: 1,
        NumberOfPeriods: 3,
        TuanHoc: '01/09/2026->15/09/2026'
      }
    ]
  };

  const events = Logic.parseSemesterSchedule(rawData);
  // Mondays between 01/09/2026 and 15/09/2026:
  // 01/09/2026 is Tuesday. Next Monday is 07/09/2026, 14/09/2026 -> 2 sessions
  assert.strictEqual(events.length, 2);
  const ev1 = events[0];
  assert.strictEqual(ev1.title, '[COMP101] Lập trình Web & Ứng dụng');
  assert.strictEqual(ev1.room, 'A1-205');
  assert.strictEqual(ev1.lecturer, 'TS. Nguyễn Văn A');
  assert.strictEqual(ev1.uid, 'hcmute-class-COMP101-20260907-p1');
  assert.strictEqual(ev1.startHour, 7);
  assert.strictEqual(ev1.startMin, 30);
  assert.strictEqual(ev1.endHour, 9);
  assert.strictEqual(ev1.endMin, 45);
});

runTest('parseExamSchedule parses exam data accurately', () => {
  const rawExams = [
    {
      CurriculumName: 'Cơ sở dữ liệu',
      CurriculumID: 'COMP102',
      NgayThi: '15/11/2026',
      GioThi: '13g30',
      ThoiLuong: 90,
      PhongThi: 'B2-101',
      DiaDiem: 'Khu A',
      KyThi: 'Cuối kỳ'
    }
  ];

  const exams = Logic.parseExamSchedule(rawExams);
  assert.strictEqual(exams.length, 1);
  const ex = exams[0];
  assert.strictEqual(ex.code, 'COMP102');
  assert.strictEqual(ex.subject, 'Cơ sở dữ liệu');
  assert.strictEqual(ex.room, 'B2-101');
  assert.strictEqual(ex.uid, 'hcmute-exam-COMP102-20261115-1330');
  assert.strictEqual(ex.startYear, 2026);
  assert.strictEqual(ex.startMonth, 11);
  assert.strictEqual(ex.startDay, 15);
  assert.strictEqual(ex.startHour, 13);
  assert.strictEqual(ex.startMin, 30);
  assert.strictEqual(ex.endHour, 15);
  assert.strictEqual(ex.endMin, 0);
});

// 3. Hot Window & Next Run Timing
console.log('\n3. Hot Window & Next Run Timing (nextRunAfter):');
runTest('Class at 07:30 creates morning hot window [06:00, 07:20] with floor at 05:00', () => {
  const classesToday = [
    { startHour: 7, startMin: 30, endHour: 11, endMin: 30 }
  ];
  const hotWindows = Logic.getHotWindowsForDay(classesToday);
  assert.strictEqual(hotWindows.length, 1);
  assert.strictEqual(hotWindows[0].startHour, 6);
  assert.strictEqual(hotWindows[0].startMin, 0);
  assert.strictEqual(hotWindows[0].endHour, 7);
  assert.strictEqual(hotWindows[0].endMin, 20);
});

runTest('Class at 12:30 (no morning class) creates afternoon hot window [11:00, 12:20] only', () => {
  const classesToday = [
    { startHour: 12, startMin: 30, endHour: 16, endMin: 30 }
  ];
  const hotWindows = Logic.getHotWindowsForDay(classesToday);
  assert.strictEqual(hotWindows.length, 1);
  assert.strictEqual(hotWindows[0].startHour, 11);
  assert.strictEqual(hotWindows[0].startMin, 0);
  assert.strictEqual(hotWindows[0].endHour, 12);
  assert.strictEqual(hotWindows[0].endMin, 20);
});

runTest('Inside hot window: nextRunAfter returns 30-45 min later or final check before class', () => {
  // Current time: 06:15 VN time
  const now = new Date('2026-10-25T06:15:00+07:00');
  const hotWindows = [{ startHour: 6, startMin: 0, endHour: 7, endMin: 20, classStartHour: 7, classStartMin: 30 }];
  
  const next = Logic.nextRunAfter(now, hotWindows, true, false, 0);
  const diffMins = (next.getTime() - now.getTime()) / (60 * 1000);
  // Between 28 and 47 mins (accounting for jitter ±2m)
  assert.ok(diffMins >= 28 && diffMins <= 67, `Expected 28-67 mins, got ${diffMins}`);
});

runTest('Day with NO classes: nextRunAfter returns 180-240 minutes later', () => {
  const now = new Date('2026-10-25T10:00:00+07:00');
  const hotWindows = [];
  const next = Logic.nextRunAfter(now, hotWindows, false, false, 0);
  const diffMins = (next.getTime() - now.getTime()) / (60 * 1000);
  assert.ok(diffMins >= 178 && diffMins <= 245, `Expected 178-245 mins, got ${diffMins}`);
});

runTest('Quiet hours (23:00 - 05:00): scan postponed to 05:00 or morning hot window', () => {
  const now = new Date('2026-10-25T23:15:00+07:00');
  const hotWindowsTomorrow = [{ startHour: 6, startMin: 0, endHour: 7, endMin: 20 }];
  const next = Logic.nextRunAfter(now, hotWindowsTomorrow, true, false, 0);
  
  // Next run must be tomorrow after 05:00
  const nextHour = next.getHours();
  assert.ok(nextHour >= 5 && nextHour <= 6, `Expected hour 5 or 6, got ${nextHour}`);
  assert.strictEqual(next.getDate(), 26);
});

runTest('Network error (429/5xx): sets nextDue = now + 30 min (max 3 times)', () => {
  const now = new Date('2026-10-25T10:00:00+07:00');
  const next = Logic.nextRunAfter(now, [], false, true, 1);
  const diffMins = (next.getTime() - now.getTime()) / (60 * 1000);
  assert.ok(diffMins >= 28 && diffMins <= 32, `Expected ~30 mins, got ${diffMins}`);
});

// 4. Color Assignment
console.log('\n4. Color Assignment (EventColor palette):');
runTest('10 distinct colors assigned sequentially and course 11 wraps around without changing previous colors', () => {
  let colorMap = {};
  const courses = [
    'COMP1', 'COMP2', 'COMP3', 'COMP4', 'COMP5',
    'COMP6', 'COMP7', 'COMP8', 'COMP9', 'COMP10',
    'COMP11'
  ];

  courses.forEach(c => {
    colorMap = Logic.assignCourseColor(c, colorMap);
  });

  // Check 10 distinct colors for first 10 courses
  const first10Colors = courses.slice(0, 10).map(c => colorMap[c]);
  const uniqueColors = new Set(first10Colors);
  assert.strictEqual(uniqueColors.size, 10);

  // 11th course gets color of 1st course (index 0)
  assert.strictEqual(colorMap['COMP11'], colorMap['COMP1']);

  // Original colors remain completely untouched
  assert.strictEqual(colorMap['COMP1'], first10Colors[0]);
  assert.strictEqual(colorMap['COMP2'], first10Colors[1]);
});

runTest('Exams always receive RED color code', () => {
  assert.strictEqual(Logic.EXAM_COLOR, 11); // Tomato/Red
});

// 5. Diffing & Event Hash Comparison
console.log('\n5. Diffing & Event Hash Comparison:');
runTest('computeScheduleHash is deterministic and detects changes', () => {
  const listA = [
    { uid: 'u1', title: 'Môn A', room: 'A1', startIso: '2026-10-26T07:30:00' }
  ];
  const listB = [
    { uid: 'u1', title: 'Môn A', room: 'A1', startIso: '2026-10-26T07:30:00' }
  ];
  const listC = [
    { uid: 'u1', title: 'Môn A', room: 'B2', startIso: '2026-10-26T07:30:00' }
  ];

  const hashA = Logic.computeScheduleHash(listA);
  const hashB = Logic.computeScheduleHash(listB);
  const hashC = Logic.computeScheduleHash(listC);

  assert.strictEqual(hashA, hashB);
  assert.notStrictEqual(hashA, hashC);
});

runTest('diffEvents identifies additions, modifications, and cancellations', () => {
  const existingInCalendar = [
    { uid: 'hcmute-class-1', title: 'Toán', room: 'A101', startIso: '2026-10-26T07:30:00', endIso: '2026-10-26T09:45:00' },
    { uid: 'hcmute-class-2', title: 'Lý', room: 'B202', startIso: '2026-10-26T10:00:00', endIso: '2026-10-26T12:15:00' }
  ];

  const newFromPortal = [
    // Class 1 changed room from A101 to A105
    { uid: 'hcmute-class-1', title: 'Toán', room: 'A105', startIso: '2026-10-26T07:30:00', endIso: '2026-10-26T09:45:00' },
    // Class 2 is cancelled (omitted)
    // Class 3 is newly added
    { uid: 'hcmute-class-3', title: 'Hóa', room: 'C303', startIso: '2026-10-27T07:30:00', endIso: '2026-10-27T09:45:00' }
  ];

  const diff = Logic.diffEvents(existingInCalendar, newFromPortal);
  assert.strictEqual(diff.toAdd.length, 1);
  assert.strictEqual(diff.toAdd[0].uid, 'hcmute-class-3');

  assert.strictEqual(diff.toUpdate.length, 1);
  assert.strictEqual(diff.toUpdate[0].uid, 'hcmute-class-1');
  assert.strictEqual(diff.toUpdate[0].newRoom, 'A105');

  assert.strictEqual(diff.toDelete.length, 1);
  assert.strictEqual(diff.toDelete[0].uid, 'hcmute-class-2');
});


// 6. Semantic Version Comparison
console.log('6. Semantic Version Comparison (compareVersions):');
runTest('compareVersions handles equal, lower, and higher versions', () => {
  assert.strictEqual(Logic.compareVersions('1.0.0', '1.0.0'), 0);
  assert.strictEqual(Logic.compareVersions('1.0.0', '1.1.0'), -1);
  assert.strictEqual(Logic.compareVersions('1.2.0', '1.1.5'), 1);
  assert.strictEqual(Logic.compareVersions('2.0.0', '1.9.9'), 1);
  assert.strictEqual(Logic.compareVersions('1.0.0', '2.0.0'), -1);
});

// 7. Portal Payload Validation
console.log('7. Portal Payload Schema Validation (validatePortalPayload):');
runTest('validatePortalPayload accepts valid schedule payload', () => {
  const good = [
    { TenHP: 'Toán', Thu: 'Thứ 2', PeriodID: 1, NumberOfPeriods: 3 }
  ];
  const res = Logic.validatePortalPayload(good);
  assert.strictEqual(res.ok, true);
  assert.strictEqual(res.items.length, 1);
});

runTest('validatePortalPayload rejects malformed or unreadable payload', () => {
  const bad = [
    { foo: 'bar', baz: 123 }
  ];
  const res = Logic.validatePortalPayload(bad);
  assert.strictEqual(res.ok, false);
});

// 8. Mass Deletion Circuit Breaker
console.log('8. Mass Deletion Circuit Breaker:');
runTest('Circuit breaker halts deletion when >= 5 events drop by > 70%', () => {
  const existing = [
    { uid: 'e1' }, { uid: 'e2' }, { uid: 'e3' }, { uid: 'e4' }, { uid: 'e5' }, { uid: 'e6' }
  ];
  const newPortal = [
    { uid: 'e1' } // Only 1 out of 6 remains (< 30%)
  ];
  const diff = Logic.diffEvents(existing, newPortal);
  assert.strictEqual(diff.circuitBreakerTriggered, true);
  assert.strictEqual(diff.toDelete.length, 0);
});

console.log(`\n========================================`);
console.log(`Test Results: ${passCount}/${testCount} passed`);
console.log(`========================================\n`);

if (passCount !== testCount) {
  process.exit(1);
}
