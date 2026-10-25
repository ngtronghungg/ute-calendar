
function safeHTML(raw) {
  if (typeof DOMPurify !== 'undefined' && DOMPurify.sanitize) {
    return DOMPurify.sanitize(raw);
  }
  return raw;
}
let appState = {
      authenticated: false,
      profile: null,
      classes: [],
      exams: [],
      considerations: [],
      selectedReminderIds: new Set(),
      currentTab: 'schedule',
      includePastSchedule: true,
      listOnlyUpcoming: true,
      includePastExams: false,
      overviewData: null,
      scheduleViewMode: 'matrix',
      currentWeekMonday: null,
      selectedDayIndex: (new Date().getDay() + 6) % 7,
      noticeFilter: 'all',
      noticeSearch: '',
    };

    // Centralized Authenticated Fetch Wrapper
    async function apiFetch(url, options = {}) {
      options.credentials = 'same-origin';
      const res = await fetch(url, options);
      if (res.status === 401 && url === '/api/status') {
        appState.authenticated = false;
        appState.profile = null;
        showLogin();
      }
      return res;
    }

    // Initialize application on load
    window.addEventListener('DOMContentLoaded', async () => {
      initCentralizedEventListeners();
      
      const cachedProfile = localStorage.getItem('hcmute_cached_profile');
      if (cachedProfile) {
        try {
          appState.profile = JSON.parse(cachedProfile);
          appState.authenticated = true;
          showDashboard();
          const cachedOverview = localStorage.getItem('hcmute_cached_overview');
          if (cachedOverview) {
            try {
              const ov = JSON.parse(cachedOverview);
              applyOverviewData(ov, true);
            } catch {}
          }
        } catch {}
      }
      await checkAuthStatus();
    });

    async function checkAuthStatus() {
      try {
        const res = await apiFetch('/api/status');
        let data;
        try {
          data = await res.json();
        } catch(e) {
          if (appState.authenticated) return;
          showLogin();
          return;
        }

        if (data.authenticated && data.profile) {
          appState.authenticated = true;
          appState.profile = data.profile;
          localStorage.setItem('hcmute_cached_profile', JSON.stringify(data.profile));
          showDashboard();
          loadOverviewData().catch(err => console.warn('Overview load error:', err));
        } else {
          localStorage.removeItem('hcmute_cached_profile');
          localStorage.removeItem('hcmute_cached_overview');
          showLogin();
        }
      } catch (err) {
        console.warn('Network issue during status check, retaining local session:', err);
      }
    }

    
    async function enterGuestSyncMode() {
      const guestGuide = document.getElementById('guestGuideBox');
      const guestNotice = document.getElementById('guestPrepNotice');
      let hasTemplate = false;
      guestGuide?.classList.add('hidden');
      guestNotice?.classList.add('hidden');
      document.getElementById('loginView')?.classList.add('hidden');
      const guestView = document.getElementById('guestSyncView');
      if (guestView) {
        guestView.classList.remove('hidden');
      }
      try {
        const res = await fetch('/api/public-config');
        if (res.ok) {
          const data = await res.json();
          if (data.auto_sync_template_url && data.auto_sync_template_url.trim()) {
            hasTemplate = true;
            let copyUrl = data.auto_sync_template_url.trim();
            if (!copyUrl.endsWith('/copy')) {
              copyUrl = copyUrl.replace(/\/(edit|view|copy)?(\?.*)?$/, '/copy');
            }
            const btnCopy = document.getElementById('guestBtnCopySheetLink');
            if (btnCopy) btnCopy.href = copyUrl;
          }
          if (data.repo_url) {
            const repoLinks = document.querySelectorAll('.repo-link');
            repoLinks.forEach(a => { a.href = data.repo_url; a.classList.remove('hidden'); });
          }
        }
      } catch (e) {
        console.warn('Lỗi tải cấu hình công khai:', e);
      }
      // Chỉ hiện hướng dẫn khi bảng mẫu thật sự tồn tại; nếu không thì báo "đang chuẩn bị"
      guestGuide?.classList.toggle('hidden', !hasTemplate);
      guestNotice?.classList.toggle('hidden', hasTemplate);
    }

    function exitGuestSyncMode() {
      document.getElementById('guestSyncView')?.classList.add('hidden');
      document.getElementById('loginView')?.classList.remove('hidden');
      document.getElementById('guestSyncView')?.classList.add('hidden');
    }

    function showLogin() {
      document.getElementById('loginView')?.classList.remove('hidden');
      document.getElementById('guestSyncView')?.classList.add('hidden');
      document.getElementById('dashboardView')?.classList.add('hidden');
      document.getElementById('mainNav')?.classList.add('hidden');
      document.getElementById('userPill')?.classList.add('hidden');
      document.getElementById('logoutBtn')?.classList.add('hidden');
    }

    function showDashboard() {
      document.getElementById('loginView')?.classList.add('hidden');
      document.getElementById('dashboardView')?.classList.remove('hidden');
      document.getElementById('guestSyncView')?.classList.add('hidden');
      document.getElementById('mainNav')?.classList.remove('hidden');
      document.getElementById('userPill')?.classList.remove('hidden');
      document.getElementById('logoutBtn')?.classList.remove('hidden');

      // Instant 0ms Week & Matrix Paint
      if (!appState.currentWeekMonday) {
        appState.currentWeekMonday = getMonday(new Date());
      }
      renderScheduleCalendar();

      if (appState.profile) {
        const userDisplay = document.getElementById('userNameDisplay');
        if (userDisplay) {
          userDisplay.textContent = `${appState.profile.name || 'Sinh viên'} (${appState.profile.id || ''})`;
        }
        const syncTitle = document.getElementById('syncUserFullTitle');
        if (syncTitle) syncTitle.textContent = `${appState.profile.name || 'Sinh viên'}`;
        const syncSub = document.getElementById('syncUserMssvSubtitle');
        if (syncSub) syncSub.textContent = `MSSV: ${appState.profile.id || ''} • ${appState.profile.status || 'Đang học'}`;
      }
    }

    function confirmLogout() {
      openUserProfileModal();
    }

    function openUserProfileModal() {
      if (!appState.profile) return;
      document.getElementById('modalUserName').textContent = appState.profile.name || 'Sinh viên';
      document.getElementById('modalUserMssv').textContent = `MSSV: ${appState.profile.id || ''}`;
      document.getElementById('modalUserRole').textContent = `Vai trò: ${appState.profile.role || 'SV'}`;
      document.getElementById('modalUserStatus').textContent = appState.profile.status || 'Đang học';
      const m = document.getElementById('userProfileModal');
      if (m) m.classList.add('open');
    }

    function closeUserProfileModal(e) {
      if (e && e.target !== e.currentTarget && !e.target.classList.contains('btn-icon') && !e.target.classList.contains('btn-secondary')) return;
      const m = document.getElementById('userProfileModal');
      if (m) m.classList.remove('open');
    }

    async function executeLogout() {
      closeUserProfileModal();
      try {
        await apiFetch('/api/logout', { method: 'POST' });
      } catch {}
      localStorage.removeItem('hcmute_cached_profile');
      localStorage.removeItem('hcmute_cached_overview');
      localStorage.clear();
      sessionStorage.clear();
      document.cookie = "hcmute_session=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";
      appState.authenticated = false;
      appState.profile = null;
      appState.classes = [];
      appState.exams = [];
      appState.considerations = [];
      showLogin();
      window.location.replace('/');
    }

    async function handleLogout() {
      executeLogout();
    }

    // Regular classes carry the internal category "ACADEMIC"; never show that word to students.
    function categoryLabel(c) {
      const labels = { ACADEMIC: 'Môn học', EXAM: 'Lịch thi', PERSONAL: 'Nhắc nhở', TUITION: 'Học phí' };
      return labels[c.category] || 'Môn học';
    }

    // A badge only helps when an event is not an ordinary class, so classes get none.
    function categoryBadge(c, color) {
      if (!c.category || c.category === 'ACADEMIC') return '';
      return `<span class="class-code" style="color: ${color}; background: ${color}22; border: 1px solid ${color}44;">${escapeHtml(categoryLabel(c))}</span>`;
    }

    let loginCooldownTimer = null;

    function formatWait(seconds) {
      return seconds < 60 ? `${seconds} giây` : `${Math.ceil(seconds / 60)} phút`;
    }

    // After repeated wrong passwords the server locks the MSSV; mirror that with a visible countdown.
    function startLoginCooldown(btn, seconds) {
      clearInterval(loginCooldownTimer);
      const until = Date.now() + seconds * 1000;
      const tick = () => {
        const left = Math.ceil((until - Date.now()) / 1000);
        if (left <= 0) {
          clearInterval(loginCooldownTimer);
          loginCooldownTimer = null;
          btn.disabled = false;
          btn.innerHTML = `<span>Đăng nhập</span>`;
          return;
        }
        btn.disabled = true;
        btn.textContent = `Thử lại sau ${formatWait(left)}`;
      };
      tick();
      loginCooldownTimer = setInterval(tick, 1000);
    }

    async function handleLogin(e) {
      e.preventDefault();
      if (loginCooldownTimer) return;
      const mssv = document.getElementById('mssvInput').value.trim();
      const pass = document.getElementById('passwordInput').value.trim();
      const btn = document.getElementById('loginSubmitBtn');
      const errorDiv = document.getElementById('loginError');

      errorDiv.classList.add('hidden');
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner"></span> <span>Đang đăng nhập...</span>`;

      try {
        const res = await fetch('/api/login', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: mssv, password: pass })
        });
        let data;
        try {
          data = await res.json();
        } catch(e) {
          errorDiv.textContent = 'Máy chủ đang khởi động lại. Vui lòng thử lại sau giây lát.';
          errorDiv.classList.remove('hidden');
          return;
        }

        if (data.success) {
          if (data.profile) {
            localStorage.setItem('hcmute_cached_profile', JSON.stringify(data.profile));
          }
          appState.authenticated = true;
          appState.profile = data.profile;
          showDashboard();
          loadOverviewData().catch(err => console.warn('Overview load error:', err));
          return;
        } else {
          errorDiv.textContent = data.message || 'Đăng nhập không thành công. Vui lòng kiểm tra lại MSSV và Mật khẩu.';
          errorDiv.classList.remove('hidden');
          if (data.retry_after) startLoginCooldown(btn, data.retry_after);
        }
      } catch (err) {
        errorDiv.textContent = 'Lỗi kết nối máy chủ: ' + err.message;
        errorDiv.classList.remove('hidden');
      } finally {
        if (!loginCooldownTimer) {
          btn.disabled = false;
          btn.innerHTML = `<span>Đăng nhập</span>`;
        }
      }
    }

    function toggleLoginMode(mode) {
      const tabPass = document.getElementById('tabLoginPass');
      const tabToken = document.getElementById('tabLoginToken');
      const formPass = document.getElementById('formLoginPass');
      const formToken = document.getElementById('formLoginToken');
      const errorDiv = document.getElementById('loginError');
      if (errorDiv) errorDiv.classList.add('hidden');

      tabPass?.classList.toggle('active', mode === 'pass');
      tabToken?.classList.toggle('active', mode === 'token');

      formPass?.classList.toggle('hidden', mode !== 'pass');
      formToken?.classList.toggle('hidden', mode !== 'token');
    }

    async function handleTokenLogin(e) {
      e.preventDefault();
      const token = document.getElementById('tokenRawInput').value.trim();
      const mssv = document.getElementById('tokenMssvInput').value.trim();
      const btn = document.getElementById('loginTokenSubmitBtn');
      const errorDiv = document.getElementById('loginError');

      if (!token) return;
      errorDiv.classList.add('hidden');
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner"></span> <span>Đang xác minh Token...</span>`;

      try {
        const res = await fetch('/api/login', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: token, username: mssv })
        });
        let data;
        try {
          data = await res.json();
        } catch(e) {
          errorDiv.textContent = 'Máy chủ đang khởi động lại. Vui lòng thử lại sau giây lát.';
          errorDiv.classList.remove('hidden');
          return;
        }
        if (data.success) {
          if (data.profile) {
            localStorage.setItem('hcmute_cached_profile', JSON.stringify(data.profile));
          }
          appState.authenticated = true;
          appState.profile = data.profile;
          showDashboard();
          loadOverviewData().catch(err => console.warn('Overview load error:', err));
          return;
        } else {
          errorDiv.textContent = data.message || 'Token không hợp lệ hoặc đã hết hạn.';
          errorDiv.classList.remove('hidden');
        }
      } catch (err) {
        errorDiv.textContent = 'Lỗi kết nối: ' + err.message;
        errorDiv.classList.remove('hidden');
      } finally {
        btn.disabled = false;
        btn.innerHTML = `<span>Xác nhận & Đồng bộ (Zero Password)</span>`;
      }
    }

    function openSecurityModal() {
      const modal = document.getElementById('securityModal');
      if (modal) modal.classList.add('open');
    }

    function closeSecurityModal(e) {
      if (e && e.target !== e.currentTarget && !e.target.classList.contains('btn-icon') && !e.target.classList.contains('btn-secondary')) return;
      const modal = document.getElementById('securityModal');
      if (modal) modal.classList.remove('open');
    }

    async function wipeMyData() {
      if (!confirm('Bạn có chắc chắn muốn xóa sạch toàn bộ phiên đăng nhập và dữ liệu lịch trên máy chủ? Bạn sẽ được đưa về màn hình đăng nhập.')) return;
      try {
        await apiFetch('/api/security/wipe-my-data', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
        closeSecurityModal();
        handleLogout();
        alert('Toàn bộ dữ liệu của bạn đã được xóa sạch hoàn toàn khỏi hệ thống (0 byte còn lại).');
      } catch (err) {
        alert('Lỗi: ' + err.message);
      }
    }

    function switchTab(tabName) {
      appState.currentTab = tabName;
      document.querySelectorAll('.nav-tabs .tab-btn').forEach(btn => btn.classList.remove('active'));
      const activeBtn = Array.from(document.querySelectorAll('.nav-tabs .tab-btn')).find(b =>
        b.dataset.tab === tabName
      );
      if (activeBtn) activeBtn.classList.add('active');

      document.getElementById('scheduleTab').classList.add('hidden');
      document.getElementById('remindersTab').classList.add('hidden');
      document.getElementById('examsTab').classList.add('hidden');
      document.getElementById('syncTab').classList.add('hidden');

      if (tabName === 'schedule') document.getElementById('scheduleTab').classList.remove('hidden');
      if (tabName === 'reminders') {
        document.getElementById('remindersTab').classList.remove('hidden');
        if (!appState.considerations || appState.considerations.length === 0) {
          loadConsiderations();
        }
      }
      if (tabName === 'exams') document.getElementById('examsTab').classList.remove('hidden');
      if (tabName === 'sync') {
        document.getElementById('syncTab').classList.remove('hidden');
        loadSyncTabInfo();
      }
    }

    function toggleSchedulePast(onlyUpcoming) {
      // Chỉ lọc ở chế độ Danh sách; lưới tuần và theo ngày luôn cần đủ dữ liệu cả kỳ.
      appState.listOnlyUpcoming = !!onlyUpcoming;
      renderScheduleCalendar();
    }

    function toggleExamsPast(onlyUpcoming) {
      appState.includePastExams = !onlyUpcoming;
      loadOverviewData();
    }

    function applyOverviewData(data, isCached = false) {
      if (!data) return;
      appState.classes = data.classes || [];
      appState.exams = data.exams || [];
      appState.overviewData = data;

      // Populate year & term dropdowns if first load
      populateSemesterSelectors(data.years, data.terms, data.year, data.term);

      const upCount = data.upcoming_classes_count ?? appState.classes.length;
      const totalCount = data.total_classes_count ?? appState.classes.length;

      const subTitleEl = document.getElementById('semesterSubtitle');
      const toggleLabelEl = document.getElementById('scheduleToggleLabel');
      if (subTitleEl && toggleLabelEl) {
        subTitleEl.textContent =
          `Học kỳ ${data.term} • Năm học ${data.year} • ${totalCount} buổi học cả kỳ`;
        const upcomingNow = appState.classes.filter(c => new Date(c.end) >= new Date()).length;
        toggleLabelEl.textContent = `Chỉ hiện lịch sắp tới (${upcomingNow})`;
      }

      const upExams = data.upcoming_exams_count ?? appState.exams.length;
      const totalExams = data.total_exams_count ?? appState.exams.length;
      const examsSub = document.getElementById('examsSubtitle');
      if (examsSub) {
        examsSub.textContent = appState.includePastExams
          ? `Tổng cộng ${totalExams} môn thi (cả môn đã thi và sắp thi)`
          : `${upExams} môn thi trong đợt này`;
      }
      if (document.getElementById('examsToggleLabel')) {
        document.getElementById('examsToggleLabel').textContent =
          appState.includePastExams ? `Hiện tất cả (${totalExams})` : `Chỉ hiện môn sắp thi (${upExams})`;
      }

      // Smart Auto-Focus Week:
      // Jump to the closest week with classes so timetable never opens to an empty screen
      if (!appState.currentWeekMonday && appState.classes && appState.classes.length > 0) {
        const now = new Date();
        const thisMonday = getMonday(now);
        const thisSunday = new Date(thisMonday);
        thisSunday.setDate(thisMonday.getDate() + 6);
        thisSunday.setHours(23, 59, 59, 999);

        const hasClassesThisWeek = appState.classes.some(c => {
          if (!c.start) return false;
          const dt = new Date(c.start);
          return dt >= thisMonday && dt <= thisSunday;
        });

        if (hasClassesThisWeek) {
          appState.currentWeekMonday = thisMonday;
        } else {
          // Find first upcoming class >= today
          const upcomingClass = appState.classes.find(c => c.start && new Date(c.start) >= now);
          if (upcomingClass) {
            appState.currentWeekMonday = getMonday(new Date(upcomingClass.start));
          } else {
            appState.currentWeekMonday = thisMonday;
          }
        }
      }

      renderScheduleCalendar();
      renderExamsGrid(appState.exams);
    }

    async function loadOverviewData(force = false) {
      const grid = document.getElementById('scheduleGrid');
      const examsGrid = document.getElementById('examsGrid');

      // If we don't have classes loaded yet, attempt to restore from cache first (0ms)
      if (!appState.classes || appState.classes.length === 0) {
        const cachedOverview = localStorage.getItem('hcmute_cached_overview');
        if (cachedOverview) {
          try {
            applyOverviewData(JSON.parse(cachedOverview), true);
          } catch {}
        } else {
          grid.innerHTML = `<div class="empty-state">Đang tải thời khóa biểu từ HCMUTE...</div>`;
        }
      }

      try {
        const yearVal = document.getElementById('yearSelect')?.value || '';
        const termVal = document.getElementById('termSelect')?.value || '';
        const includePast = appState.includePastSchedule ? 'true' : 'false';
        const includePastExams = appState.includePastExams ? 'true' : 'false';
        const url = `/api/overview?year=${encodeURIComponent(yearVal)}&term=${encodeURIComponent(termVal)}&include_past=${includePast}&include_past_exams=${includePastExams}`;

        const res = await apiFetch(url);
        let data;
        try {
          data = await res.json();
        } catch(e) {
          if (!appState.classes || appState.classes.length === 0) {
            grid.innerHTML = `<div class="empty-state">Máy chủ đang phản hồi chậm hoặc đang khởi động. Vui lòng thử lại sau giây lát.</div>`;
          }
          return;
        }
        if (!data || !data.success) {
          throw new Error(data?.message || 'Không thể đồng bộ dữ liệu lúc này.');
        }

        applyOverviewData(data);
        try {
          localStorage.setItem('hcmute_cached_overview', JSON.stringify(data));
        } catch {}
      } catch (err) {
        if (!appState.classes || appState.classes.length === 0) {
          grid.innerHTML = `<div class="empty-state">Không thể tải TKB: ${err.message}</div>`;
        }
      }
    }

    function populateSemesterSelectors(years, terms, currentYear, currentTerm) {
      const ySelect = document.getElementById('yearSelect');
      const tSelect = document.getElementById('termSelect');
      if (!ySelect || !tSelect) return;

      if (ySelect.children.length === 0 && Array.isArray(years)) {
        ySelect.innerHTML = years.map(y => `<option value="${y}" ${y === currentYear ? 'selected' : ''}>Năm học ${y}</option>`).join('');
      }
      if (tSelect.children.length === 0 && Array.isArray(terms)) {
        tSelect.innerHTML = terms.map(t => `<option value="${t.TermID}" ${t.TermID === currentTerm ? 'selected' : ''}>${t.TermName || t.TermID}</option>`).join('');
      }
    }

    function onSemesterChange() {
      loadOverviewData(true);
    }

    function escapeHtml(str) {
      if (str === null || str === undefined) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function formatDateYMD(d) {
      const year = d.getFullYear();
      const month = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      return `${year}-${month}-${day}`;
    }

    function getCourseHexColor(title) {
      if (!title) return '#0284c7';
      const clean = title.replace(/\[.*?\]|\(.*?\)/g, '').trim().toLowerCase() || title.toLowerCase();
      const palette = ['#B9806B', '#A39162', '#7F9A7C', '#6F95A0', '#8D82A8', '#B07F8E', '#9A9A6A', '#8A8F96'];
      let h = 0;
      for (let i = 0; i < clean.length; i++) {
        h = (h * 37 + clean.charCodeAt(i) * (i + 7)) & 0xFFFFFFFF;
      }
      return palette[Math.abs(h) % palette.length];
    }

    // ==========================================
    // CALENDAR APP ENGINE (THỨ / BUỔI / TUẦN)
    // ==========================================

    function getMonday(d) {
      const date = new Date(d);
      const day = date.getDay();
      const diff = date.getDate() - day + (day === 0 ? -6 : 1);
      const monday = new Date(date.setDate(diff));
      monday.setHours(0, 0, 0, 0);
      return monday;
    }

    function formatDateShort(d) {
      return d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' });
    }

    function navScheduleWeek(offset) {
      if (!appState.currentWeekMonday) {
        appState.currentWeekMonday = getMonday(new Date());
      }
      appState.currentWeekMonday.setDate(appState.currentWeekMonday.getDate() + offset * 7);
      renderScheduleCalendar();
    }

    function navScheduleToday() {
      appState.currentWeekMonday = getMonday(new Date());
      appState.selectedDayIndex = (new Date().getDay() + 6) % 7;
      renderScheduleCalendar();
    }

    function setScheduleViewMode(mode) {
      appState.scheduleViewMode = mode;
      document.getElementById('btnViewMatrix')?.classList.toggle('active', mode === 'matrix');
      document.getElementById('btnViewDay')?.classList.toggle('active', mode === 'day');
      document.getElementById('btnViewList')?.classList.toggle('active', mode === 'list');

      document.getElementById('scheduleMatrixView')?.classList.toggle('hidden', mode !== 'matrix');
      document.getElementById('scheduleDayView')?.classList.toggle('hidden', mode !== 'day');
      document.getElementById('scheduleListView')?.classList.toggle('hidden', mode !== 'list');

      renderScheduleCalendar();
    }

    function setMobileDay(idx) {
      appState.selectedDayIndex = idx;
      renderScheduleCalendar();
    }

    function renderScheduleCalendar() {
      if (!appState.currentWeekMonday) {
        appState.currentWeekMonday = getMonday(new Date());
      }

      const mon = new Date(appState.currentWeekMonday);
      const sun = new Date(mon.getTime() + 6 * 86400000);
      const now = new Date();
      now.setHours(0, 0, 0, 0);
      const isCurrentWeek = now >= mon && now <= new Date(sun.getTime() + 86399999);

      // 1. Update Title in Navigation bar
      const displayTitle = document.getElementById('calWeekDisplayTitle');
      if (displayTitle) {
        const monStr = formatDateShort(mon);
        const sunStr = formatDateShort(sun);
        const yearStr = mon.getFullYear();
        displayTitle.innerHTML = `
          <span>Tuần: <strong>${monStr} – ${sunStr}/${yearStr}</strong></span>
          ${isCurrentWeek ? '<span style="color: var(--accent); font-size: 12px; margin-left: 6px;">Tuần này</span>' : ''}
        `;
      }

      // 2. Render Mobile Day Selector Strip
      const dayShorts = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'];
      const dayStrip = document.getElementById('mobileDayStrip');
      if (dayStrip) {
        dayStrip.innerHTML = dayShorts.map((shortName, i) => {
          const d = new Date(mon);
          d.setDate(mon.getDate() + i);
          const isToday = d.getTime() === now.getTime();
          const isActive = i === appState.selectedDayIndex;
          return `
            <div class="mobile-day-btn ${isActive ? 'active' : ''} ${isToday ? 'is-today' : ''}" data-action="set-mobile-day" data-day="${i}">
              <span style="font-weight: 500;">${shortName}</span>
              <span style="font-size: 10px;">${d.getDate()}/${d.getMonth() + 1}</span>
            </div>
          `;
        }).join('');
      }

      // 3. Render Views based on mode
      if (appState.scheduleViewMode === 'matrix') {
        renderScheduleMatrix();
      } else if (appState.scheduleViewMode === 'day') {
        renderScheduleDayView();
      } else if (appState.scheduleViewMode === 'list') {
        const nowDt = new Date();
        const listItems = appState.listOnlyUpcoming
          ? appState.classes.filter(c => new Date(c.end) >= nowDt)
          : appState.classes;
        renderScheduleGrid(listItems);
      }
    }

    function renderScheduleMatrix() {
      const container = document.getElementById('scheduleMatrixView');
      if (!container) return;

      const mon = new Date(appState.currentWeekMonday);
      const now = new Date();
      now.setHours(0, 0, 0, 0);

      const dayNames = ['Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy', 'Chủ Nhật'];
      const dayDates = [];
      for (let i = 0; i < 7; i++) {
        const d = new Date(mon);
        d.setDate(mon.getDate() + i);
        dayDates.push(d);
      }

      // 3 Sessions per day
      const sessions = [
        { id: 'morning', name: 'Buổi Sáng', period: 'Tiết 1 – 6', time: '07:30 – 12:15' },
        { id: 'afternoon', name: 'Buổi Chiều', period: 'Tiết 7 – 12', time: '12:45 – 17:30' },
        { id: 'evening', name: 'Buổi Tối', period: 'Tiết 13 – 16', time: '18:00 – 21:00' },
      ];

      // Ultra-fast O(1) Pre-indexing of classes by (YYYY-MM-DD + session)
      const classMap = {};
      (appState.classes || []).forEach(c => {
        if (!c.start) return;
        const dtStr = c.start.slice(0, 10);
        const h = parseInt(c.start.slice(11, 13) || '0', 10) + (parseInt(c.start.slice(14, 16) || '0', 10) / 60);
        let sId = 'morning';
        if (h >= 17.5) sId = 'evening';
        else if (h >= 12.0) sId = 'afternoon';
        const key = `${dtStr}_${sId}`;
        if (!classMap[key]) classMap[key] = [];
        classMap[key].push(c);
      });

      // Build Table HTML
      let html = `<table class="matrix-table">`;
      
      // Header Row (Days of Week)
      html += `<thead><tr>`;
      html += `<th class="matrix-session-th" style="background: var(--bg-subtle); font-size: 12px; color: var(--text-muted);">Buổi / Thứ</th>`;
      dayDates.forEach((d, idx) => {
        const isToday = d.getTime() === now.getTime();
        html += `
          <th class="matrix-th ${isToday ? 'today-col' : ''}">
            <div style="font-size: 13px; font-weight: 500; color: ${isToday ? 'var(--accent)' : 'var(--text)'};">
              ${dayNames[idx]}
            </div>
            <div style="font-size: 11px; color: ${isToday ? 'var(--accent)' : 'var(--text-muted)'}; margin-top: 2px;">
              ${d.getDate()}/${d.getMonth() + 1}
              ${isToday ? '<span style="color: var(--accent); font-size: 11px; margin-left: 4px;">Hôm nay</span>' : ''}
            </div>
          </th>
        `;
      });
      html += `</tr></thead><tbody>`;

      // Session Rows (Sáng, Chiều, Tối)
      sessions.forEach(sess => {
        html += `<tr>`;
        html += `
          <td class="matrix-session-th">
            
            <div style="font-size: 12px; font-weight: 500; color: var(--text);">${sess.name}</div>
            <div style="font-size: 10px; color: var(--text-muted); margin-top: 2px;">${sess.period}</div>
            <div style="font-size: 9.5px; color: var(--text-subtle);">${sess.time}</div>
          </td>
        `;

        // 7 Day Cells for this session
        dayDates.forEach(d => {
          const isToday = d.getTime() === now.getTime();
          const dayYMD = formatDateYMD(d);
          const matchingClasses = classMap[`${dayYMD}_${sess.id}`] || [];

          html += `<td class="matrix-td ${isToday ? 'today-col' : ''}">`;
          if (matchingClasses.length === 0) {
            html += `<div style="height: 100%; display: flex; align-items: center; justify-content: center; color: var(--text-subtle); opacity: 0.4; font-size: 14px;">—</div>`;
          } else {
            matchingClasses.forEach(c => {
              const startDt = new Date(c.start);
              const endDt = new Date(c.end);
              const timeStr = `${startDt.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })} - ${endDt.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}`;
              const courseColor = c.color_hex || getCourseHexColor(c.title);
              const room = c.location ? c.location.split(',')[0].trim() : 'Phòng học';
              const isCancelled = !!c.is_cancelled;

              html += `
                <div class="matrix-card-chip ${isCancelled ? 'cancelled' : ''}" style="border-left-color: ${courseColor};" data-action="open-class" data-uid="${c.uid}" title="Nhấp để xem chi tiết buổi học">
                  <div class="matrix-chip-title" style="${isCancelled ? 'text-decoration: line-through; opacity: 0.6;' : ''}"><span class="course-dot" style="background: ${courseColor};"></span>${escapeHtml(c.title)}
                  </div>
                  <div class="matrix-chip-meta">
                    <span style="font-family: var(--font-mono); font-size: 10.5px;">${timeStr}</span>
                    <span class="room-badge" style="background: ${courseColor}18; color: var(--text); border-color: ${courseColor}35;">
                      ${escapeHtml(room)}
                    </span>
                  </div>
                  ${isCancelled ? '<div class="status-tag warn" style="margin-top: 4px;">Nghỉ dạy</div>' : ''}
                </div>
              `;
            });
          }
          html += `</td>`;
        });

        html += `</tr>`;
      });

      html += `</tbody></table>`;
      container.innerHTML = html;
    }

    function renderScheduleDayView() {
      const container = document.getElementById('scheduleDayView');
      if (!container) return;

      const mon = new Date(appState.currentWeekMonday);
      const now = new Date();
      now.setHours(0, 0, 0, 0);

      const dayNames = ['Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy', 'Chủ Nhật'];
      const sessions = [
        { id: 'morning', name: 'Buổi Sáng', time: '07:30 – 12:15' },
        { id: 'afternoon', name: 'Buổi Chiều', time: '12:45 – 17:30' },
        { id: 'evening', name: 'Buổi Tối', time: '18:00 – 21:00' },
      ];

      // On mobile render the currently selected day tab; on desktop render all 7 days
      const isMobile = window.innerWidth < 860;
      const daysToRender = isMobile ? [appState.selectedDayIndex] : [0, 1, 2, 3, 4, 5, 6];

      container.innerHTML = daysToRender.map(idx => {
        const d = new Date(mon);
        d.setDate(mon.getDate() + idx);
        const isToday = d.getTime() === now.getTime();
        const dayYMD = formatDateYMD(d);

        let sessionHtml = '';
        sessions.forEach(sess => {
          const matchingClasses = (appState.classes || []).filter(c => {
            if (!c.start) return false;
            const cStart = new Date(c.start);
            if (formatDateYMD(cStart) !== dayYMD) return false;
            const hour = cStart.getHours() + (cStart.getMinutes() / 60);
            if (sess.id === 'morning') return hour < 12.0;
            if (sess.id === 'afternoon') return hour >= 12.0 && hour < 17.5;
            if (sess.id === 'evening') return hour >= 17.5;
            return false;
          });

          if (matchingClasses.length > 0) {
            sessionHtml += `
              <div class="day-session-section">
                <div class="day-session-label">
                  
                  <span>${sess.name}</span>
                  <span style="font-weight: 400; text-transform: none; opacity: 0.7;">(${sess.time})</span>
                </div>
                <div style="display: flex; flex-direction: column; gap: 10px;">
                  ${matchingClasses.map(c => {
                    const startDt = new Date(c.start);
                    const endDt = new Date(c.end);
                    const timeStr = `${startDt.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })} - ${endDt.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}`;
                    const courseColor = c.color_hex || getCourseHexColor(c.title);
                    const isCancelled = !!c.is_cancelled;

                    return `
                      <div class="class-card" style="border-left: 2px solid ${courseColor}; cursor: pointer; padding: 14px 16px;" data-action="open-class" data-uid="${c.uid}">
                        <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 8px;">
                          <div>
                            ${categoryBadge(c, courseColor)}
                            <h4 style="font-size: 15px; font-weight: 500; color: var(--text); margin-top: 4px; ${isCancelled ? 'text-decoration: line-through; opacity: 0.6;' : ''}">
                              ${escapeHtml(c.title)}
                            </h4>
                          </div>
                          <span class="room-badge">${escapeHtml(c.location ? c.location.split(',')[0] : 'Phòng')}</span>
                        </div>
                        <div style="display: flex; align-items: center; justify-content: space-between; font-size: 12px; color: var(--text-muted); margin-top: 10px; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 8px;">
                          <span>${timeStr}</span>
                          <span>${escapeHtml(c.location)}</span>
                        </div>
                        ${isCancelled ? '<div class="status-tag warn" style="margin-top: 6px;">Đã đánh dấu giảng viên cho nghỉ</div>' : ''}
                      </div>
                    `;
                  }).join('')}
                </div>
              </div>
            `;
          }
        });

        if (!sessionHtml) {
          sessionHtml = `<div style="text-align: center; padding: 20px; color: var(--text-muted); font-size: 13px;">Không có ca học nào trong ngày này.</div>`;
        }

        return `
          <div class="day-view-card" >
            <div class="day-view-header">
              <div class="day-view-title">
                <span>${dayNames[idx]}, ${d.getDate()}/${d.getMonth() + 1}/${d.getFullYear()}</span>
                ${isToday ? '<span style="color: var(--accent); font-size: 12px; margin-left: 6px;">Hôm nay</span>' : ''}
              </div>
            </div>
            <div>
              ${sessionHtml}
            </div>
          </div>
        `;
      }).join('');
    }

    // Class Detail Modal Logic
    let currentSelectedClassUid = null;

    function openClassDetailModal(uid) {
      const c = (appState.classes || []).find(x => x.uid === uid);
      if (!c) return;

      currentSelectedClassUid = uid;
      const startDt = new Date(c.start);
      const endDt = new Date(c.end);
      const dayNames = ['Chủ Nhật', 'Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy'];
      const dayName = dayNames[startDt.getDay()];
      const dateStr = startDt.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' });
      const timeStr = `${startDt.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })} - ${endDt.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}`;
      
      const hour = startDt.getHours();
      const sessName = hour < 12 ? 'Buổi Sáng' : (hour < 17.5 ? 'Buổi Chiều' : 'Buổi Tối');
      const courseColor = c.color_hex || getCourseHexColor(c.title);
      const isCancelled = !!c.is_cancelled;

      document.getElementById('modalClassTitle').textContent = c.title;
      document.getElementById('modalClassCode').textContent = categoryLabel(c);
      document.getElementById('modalClassColorDot').style.background = courseColor;
      document.getElementById('modalClassDayStr').textContent = `${dayName}, ${dateStr}`;
      document.getElementById('modalClassTimeStr').textContent = `${sessName} • ${timeStr}`;
      document.getElementById('modalClassRoom').textContent = c.location ? c.location.split(',')[0].trim() : 'Phòng học';
      document.getElementById('modalClassLocation').textContent = c.location || 'HCMUTE';

      const descBox = document.getElementById('modalClassDescBox');
      if (c.description) {
        descBox.textContent = c.description;
        descBox.classList.remove('hidden');
      } else {
        descBox.classList.add('hidden');
      }

      const alertBox = document.getElementById('modalClassStatusAlert');
      const cancelBtn = document.getElementById('modalClassCancelBtn');

      if (isCancelled) {
        alertBox.className = 'banner error';
        alertBox.textContent = 'Buổi học này đang được đánh dấu giảng viên cho nghỉ.';
        alertBox.classList.remove('hidden');
        cancelBtn.textContent = 'Khôi phục buổi học';
        cancelBtn.style.color = 'var(--warn)';
        cancelBtn.onclick = () => { toggleCancelSession(uid, false); closeClassDetailModal(); };
      } else {
        alertBox.classList.add('hidden');
        cancelBtn.textContent = 'Đánh dấu giảng viên cho nghỉ';
        cancelBtn.style.color = 'var(--accent)';
        cancelBtn.onclick = () => { toggleCancelSession(uid, true); closeClassDetailModal(); };
      }

      document.getElementById('classDetailModal')?.classList.add('open');
    }

    function closeClassDetailModal(e) {
      if (e && e.target !== e.currentTarget && !e.target.classList.contains('btn-icon') && !e.target.classList.contains('btn-primary')) return;
      document.getElementById('classDetailModal')?.classList.remove('open');
    }

    function renderScheduleGrid(classes) {
      const grid = document.getElementById('scheduleGrid');
      if (!grid) return;
      if (!classes || classes.length === 0) {
        grid.innerHTML = `<div class="empty-state">Không có lịch học nào trong danh sách.</div>`;
        return;
      }

      const now = new Date();
      grid.innerHTML = classes.map(c => {
        const startDt = new Date(c.start);
        const endDt = new Date(c.end);
        const dayStr = startDt.toLocaleDateString('vi-VN', { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' });
        const timeStr = `${startDt.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })} - ${endDt.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}`;

        const isUpcoming = endDt >= now;
        const diffMs = startDt - now;
        const diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));
        const isCancelled = !!c.is_cancelled;
        const courseColor = c.color_hex || getCourseHexColor(c.title);

        let badge = '';
        let cardStyle = '';

        if (isCancelled) {
          badge = `<span class="priority-pill" style="margin-left: auto; color: var(--warn); border: 1px solid rgba(239, 68, 68, 0.3);">Nghỉ dạy</span>`;
          cardStyle = 'opacity: 0.6; border-left: 2px solid var(--warn);';
        } else if (isUpcoming) {
          if (diffDays === 0) {
            badge = `<span class="priority-pill high" style="margin-left: auto;">Hôm nay</span>`;
          } else if (diffDays === 1) {
            badge = `<span class="priority-pill high" style="margin-left: auto;">Ngày mai</span>`;
          } else if (diffDays <= 7) {
            badge = `<span class="priority-pill medium" style="margin-left: auto;">Còn ${diffDays} ngày</span>`;
          } else {
            badge = `<span class="priority-pill" style="margin-left: auto; background: var(--surface); color: var(--accent); border: 1px solid var(--line);">Sau ${diffDays} ngày</span>`;
          }
          cardStyle = `border-left: 2px solid ${courseColor};`;
        } else {
          badge = `<span style="font-size: 10px; color: var(--text-muted); margin-left: auto; font-family: var(--font-mono);">ĐÃ HỌC</span>`;
          cardStyle = `opacity: 0.55; border-left: 2px solid ${courseColor};`;
        }

        const cancelActionBtn = isCancelled
          ? `<button class="btn-secondary" style="padding: 4px 10px; font-size: 11px; margin-top: 10px; color: var(--warn); border-color: var(--line);" data-action="cancel-session" data-uid="${c.uid}" data-cancel="false">Khôi phục buổi học</button>`
          : `<button class="btn-secondary" style="padding: 4px 10px; font-size: 11px; margin-top: 10px; color: var(--warn); border-color: rgba(239, 68, 68, 0.2);" data-action="cancel-session" data-uid="${c.uid}" data-cancel="true" title="Đánh dấu nếu Giảng viên / Khoa thông báo cho nghỉ buổi học này">Đánh dấu giảng viên cho nghỉ</button>`;

        return `
          <div class="class-card" style="${cardStyle} cursor: pointer;" data-action="open-class" data-uid="${c.uid}">
            <div>
              <div style="display: flex; align-items: center; margin-bottom: 8px;">
                ${categoryBadge(c, courseColor)}
                ${badge}
              </div>
              <h3 class="class-title" style="${isCancelled ? 'text-decoration: line-through; opacity: 0.7;' : ''}">${escapeHtml(c.title)}</h3>
            </div>
            <div class="class-meta">
              <div class="meta-row">
                <span>${dayStr}</span>
                <span class="room-badge">${escapeHtml(c.location.split(',')[0] || 'Phòng')}</span>
              </div>
              <div class="meta-row">
                <span>Giờ học: ${timeStr}</span>
              </div>
              <div class="meta-row" style="color: var(--text-subtle); font-size: 11px;">
                <span>${escapeHtml(c.location)}</span>
              </div>
              <div>
                ${cancelActionBtn}
              </div>
            </div>
          </div>
        `;
      }).join('');
    }

    function renderExamsGrid(exams) {
      const grid = document.getElementById('examsGrid');
      if (!grid) return;

      const now = new Date();
      const heroEl = document.getElementById('examCountdownHero');
      const upcomingSorted = (exams || [])
        .filter(e => new Date(e.start) >= now)
        .sort((a, b) => new Date(a.start) - new Date(b.start));

      if (heroEl) {
        if (upcomingSorted.length > 0) {
          const nextExam = upcomingSorted[0];
          const nextDt = new Date(nextExam.start);
          const diffMs = nextDt - now;
          const totalSec = Math.max(0, Math.floor(diffMs / 1000));
          const days = Math.floor(totalSec / 86400);
          const hours = Math.floor((totalSec % 86400) / 3600);
          const minutes = Math.floor((totalSec % 3600) / 60);

          heroEl.classList.remove('hidden');
          heroEl.innerHTML = `
            <div class="exam-hero-header">
              <span class="exam-hero-badge">Môn thi kế tiếp</span>
              <span class="priority-pill high">${days === 0 ? 'Hôm nay' : (days === 1 ? 'Ngày mai' : 'Còn ' + days + ' ngày')}</span>
            </div>
            <div class="exam-hero-title">${nextExam.title}</div>
            <div class="exam-timer-grid">
              <div class="timer-unit">
                <div class="timer-unit-num">${String(days).padStart(2, '0')}</div>
                <div class="timer-unit-label">Ngày</div>
              </div>
              <div class="timer-unit">
                <div class="timer-unit-num">${String(hours).padStart(2, '0')}</div>
                <div class="timer-unit-label">Giờ</div>
              </div>
              <div class="timer-unit">
                <div class="timer-unit-num">${String(minutes).padStart(2, '0')}</div>
                <div class="timer-unit-label">Phút</div>
              </div>
            </div>
            <div class="exam-meta-pills">
              <div class="exam-meta-pill">${nextDt.toLocaleDateString('vi-VN', { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' })}</div>
              <div class="exam-meta-pill">${nextDt.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}</div>
              <div class="exam-meta-pill">${nextExam.location}</div>
            </div>
          `;
        } else {
          heroEl.classList.add('hidden');
        }
      }

      const filteredExams = appState.includePastExams
        ? (exams || [])
        : (exams || []).filter(e => new Date(e.start) >= now);

      if (filteredExams.length === 0) {
        grid.innerHTML = `<div class="empty-state">${appState.includePastExams ? 'Chưa có dữ liệu lịch thi.' : 'Không có môn thi sắp tới trong đợt này.'}</div>`;
        return;
      }

      grid.innerHTML = filteredExams.map(e => {
        const startDt = new Date(e.start);
        const isUpcoming = startDt >= now;
        const diffMs = startDt - now;
        const diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));

        let statusBadge = '';
        let cardStyle = '';

        if (isUpcoming) {
          if (diffDays <= 3) {
            statusBadge = `<span class="priority-pill high" style="margin-left: auto; background: var(--surface); border: 1px solid var(--line); color: #fff; font-weight: 500; ">Sắp thi (${diffDays === 0 ? 'Hôm nay' : 'Còn ' + diffDays + ' ngày'})</span>`;
            cardStyle = 'border-left: 2px solid var(--accent); background: var(--surface); ';
          } else {
            statusBadge = `<span class="priority-pill medium" style="margin-left: auto; color: var(--warn); border: 1px solid rgba(239, 68, 68, 0.4);">Còn ${diffDays} ngày</span>`;
            cardStyle = 'border-left: 2px solid var(--accent); background: var(--surface); ';
          }
        } else {
          statusBadge = `<span style="font-size: 10px; color: var(--text-muted); margin-left: auto; font-family: var(--font-mono);">ĐÃ THI</span>`;
          cardStyle = 'opacity: 0.55; border-left: 2px solid var(--line);';
        }

        return `
          <div class="class-card" style="${cardStyle}">
            <div>
              <div style="display: flex; align-items: center; margin-bottom: 8px;">
                <span class="class-code" style="color: #fff; background: var(--surface); border: 1px solid var(--line); font-weight: 500; padding: 3px 10px; border-radius: 6px; letter-spacing: 0.5px; margin-bottom: 0;">Lịch thi</span>
                ${statusBadge}
              </div>
              <h3 class="class-title" style="color: var(--text); font-weight: 500;">${e.title}</h3>
            </div>
            <div class="class-meta">
              <div class="meta-row">
                <span>Ngày thi: ${startDt.toLocaleDateString('vi-VN', { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' })}</span>
                <span class="room-badge" style="background: rgba(220, 38, 38, 0.25); color: #fca5a5; border-color: rgba(220, 38, 38, 0.4);">${e.location.split(',')[0]}</span>
              </div>
              <div class="meta-row">
                <span style="font-weight: 600; color: var(--text);">Giờ thi: ${startDt.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}</span>
              </div>
              <div class="meta-row" style="color: var(--text-subtle); font-size: 11px;">
                <span>${e.location}</span>
              </div>
            </div>
          </div>
        `;
      }).join('');
    }

    function updateNoticeCounters() {
      const all = appState.considerations || [];
      const personalCount = all.filter(it => it.notice_type === 'personal' || it.category === 'PERSONAL').length;
      const examCount = all.filter(it => it.notice_type === 'exam' || it.category === 'EXAM').length;
      const tuitionCount = all.filter(it => it.category === 'TUITION' || (it.title && it.title.toLowerCase().includes('học phí'))).length;
      const generalCount = all.filter(it => it.notice_type === 'general' && it.category !== 'TUITION' && it.category !== 'EXAM').length;

      const elP = document.getElementById('countPersonalNotices');
      if (elP) elP.textContent = personalCount;
      const elE = document.getElementById('countExamNotices');
      if (elE) elE.textContent = examCount;
      const elG = document.getElementById('countGeneralNotices');
      if (elG) elG.textContent = generalCount;

      const bAll = document.getElementById('badgeAll');
      if (bAll) bAll.textContent = all.length;
      const bP = document.getElementById('badgePersonal');
      if (bP) bP.textContent = personalCount;
      const bE = document.getElementById('badgeExam');
      if (bE) bE.textContent = examCount;
      const bT = document.getElementById('badgeTuition');
      if (bT) bT.textContent = tuitionCount;
      const bG = document.getElementById('badgeGeneral');
      if (bG) bG.textContent = generalCount;
    }

    function setNoticeFilter(filterType) {
      appState.noticeFilter = filterType;
      document.querySelectorAll('.filter-chip').forEach(btn => btn.classList.remove('active'));
      const activeBtn = document.getElementById(`chip${filterType.charAt(0).toUpperCase() + filterType.slice(1)}`);
      if (activeBtn) activeBtn.classList.add('active');
      renderConsiderationsList();
    }

    function onNoticeSearchChange(query) {
      appState.noticeSearch = (query || '').trim().toLowerCase();
      renderConsiderationsList();
    }

    async function loadConsiderations(force = false) {
      const list = document.getElementById('remindersList');
      if (!list) return;

      // If already cached in state and not forcing refresh, render immediately in 0ms
      if (!force && appState.considerations && appState.considerations.length > 0) {
        renderConsiderationsList();
        return;
      }

      list.innerHTML = `<div class="empty-state">Đang tổng hợp hộp thư cá nhân, kiểm tra học phí và quét thông báo học vụ...</div>`;

      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 9000); // 9 seconds client timeout

        const res = await apiFetch('/api/considerations' + (force ? '?force=1' : ''), {
          signal: controller.signal
        });
        clearTimeout(timeoutId);

        let data;
        try {
          data = await res.json();
        } catch(e) {
          throw new Error('Dữ liệu phản hồi không hợp lệ');
        }
        if (!data || !data.success) throw new Error(data?.message || 'Không thể tải thông báo');

        appState.considerations = data.items || [];
        const badge = document.getElementById('reminderCountBadge');
        if (badge) badge.textContent = appState.considerations.length;

        // Auto-select needed items by default
        appState.selectedReminderIds = new Set(
          appState.considerations.filter(it => it.is_needed).map(it => it.id)
        );
        updateSelectedCounter();
        renderConsiderationsList();
      } catch (err) {
        console.warn('Considerations scan notice:', err);
        list.innerHTML = `
          <div class="empty-state">
            
            <div style="font-size: 13.5px; color: var(--text-muted); margin-bottom: 8px;">
              ${err.name === 'AbortError' ? 'Cổng Portal trường đang phản hồi chậm.' : 'Chưa có thông báo nào cần nhắc nhở.'}
            </div>
            <button class="btn-secondary" style="padding: 6px 14px; font-size: 12px;" data-action="refresh-notices">
              Quét lại thông báo
            </button>
          </div>`;
      }
    }

    function renderConsiderationsList() {
      const list = document.getElementById('remindersList');
      if (!list) return;

      const all = appState.considerations || [];
      updateNoticeCounters();

      // 1. Filter by category
      let filtered = all;
      const filter = appState.noticeFilter || 'all';
      if (filter === 'personal') {
        filtered = filtered.filter(it => it.notice_type === 'personal' || it.category === 'PERSONAL');
      } else if (filter === 'exam') {
        filtered = filtered.filter(it => it.notice_type === 'exam' || it.category === 'EXAM');
      } else if (filter === 'tuition') {
        filtered = filtered.filter(it => it.category === 'TUITION' || (it.title && it.title.toLowerCase().includes('học phí')));
      } else if (filter === 'general') {
        filtered = filtered.filter(it => it.notice_type === 'general' && it.category !== 'TUITION' && it.category !== 'EXAM');
      }

      // 2. Filter by search query
      const search = appState.noticeSearch;
      if (search) {
        filtered = filtered.filter(it => {
          const t = (it.title || '').toLowerCase();
          const s = (it.sender || '').toLowerCase();
          const a = (it.action || '').toLowerCase();
          const r = (it.recommendation || '').toLowerCase();
          return t.includes(search) || s.includes(search) || a.includes(search) || r.includes(search);
        });
      }

      if (filtered.length === 0) {
        if (all.length === 0) {
          list.innerHTML = `<div class="empty-state">Hiện tại bạn không có thông báo hay hạn chót nào trong hộp thư.</div>`;
        } else {
          list.innerHTML = `<div class="empty-state">Không tìm thấy thông báo nào phù hợp với bộ lọc hoặc từ khóa "${escapeHtml(search)}".</div>`;
        }
        return;
      }

      list.innerHTML = filtered.map(it => {
        const isSelected = appState.selectedReminderIds.has(it.id);
        const isHigh = it.priority === 'HIGH';
        const cardClass = isHigh ? 'reminder-card high-priority' : 'reminder-card medium-priority';

        let typePill = '';
        if (it.notice_type === 'personal' || it.category === 'PERSONAL') {
          typePill = `<span class="notice-type-pill personal">Hộp thư cá nhân</span>`;
        } else if (it.notice_type === 'exam' || it.category === 'EXAM') {
          typePill = `<span class="notice-type-pill exam">Lịch thi</span>`;
        } else if (it.category === 'TUITION' || (it.title && it.title.toLowerCase().includes('học phí'))) {
          typePill = `<span class="notice-type-pill tuition">Học phí</span>`;
        } else {
          typePill = `<span class="notice-type-pill general">Thông báo trường</span>`;
        }

        let countdownPill = '';
        if (it.days_left !== null && it.days_left !== undefined) {
          if (it.days_left <= 0) {
            countdownPill = `<span class="priority-pill high">Hôm nay</span>`;
          } else if (it.days_left === 1) {
            countdownPill = `<span class="priority-pill high">Ngày mai</span>`;
          } else if (it.days_left <= 3) {
            countdownPill = `<span class="priority-pill high">Còn ${it.days_left} ngày</span>`;
          } else if (it.days_left <= 10) {
            countdownPill = `<span class="priority-pill medium">Còn ${it.days_left} ngày</span>`;
          } else {
            countdownPill = `<span class="priority-pill" style="background: var(--surface); color: var(--accent); border: 1px solid var(--line);">Còn ${it.days_left} ngày</span>`;
          }
        } else {
          countdownPill = `<span class="priority-pill" style="background: rgba(255, 255, 255, 0.06); color: var(--text-subtle); border: 1px solid var(--surface-border);">Tin học vụ</span>`;
        }

        const senderStr = it.sender ? `${escapeHtml(it.sender)}` : '';
        const dateStr = it.source_date ? `Đăng ngày ${escapeHtml(it.source_date)}` : '';
        const metaInfo = [senderStr, dateStr].filter(Boolean).join(' • ');

        return `
          <div class="${cardClass}">
            <div class="reminder-content">
              <div class="reminder-header" style="flex-wrap: wrap;">
                ${typePill}
                ${countdownPill}
                ${it.deadline ? `<span class="deadline-pill">Hạn chót: ${escapeHtml(it.deadline)}</span>` : ''}
              </div>
              <h4 class="reminder-title" style="cursor: pointer; margin-top: 6px;" data-action="open-notice" data-id="${it.id}" data-type="${it.notice_type || 'general'}">${escapeHtml(it.title)}</h4>
              ${metaInfo ? `<div style="font-size: 11.5px; color: var(--text-muted); margin-bottom: 8px;">${metaInfo}</div>` : ''}
              <p class="reminder-action">${escapeHtml(it.action)}</p>
              <p class="reminder-reason">${escapeHtml(it.recommendation)}</p>
              <div style="display: flex; gap: 8px; margin-top: 12px; align-items: center; flex-wrap: wrap;">
                <button class="btn-secondary" style="padding: 5px 12px; font-size: 12px;" data-action="open-notice" data-id="${it.id}" data-type="${it.notice_type || 'general'}">
                  Xem chi tiết thông báo
                </button>
              </div>
            </div>
            <label class="ios-switch" title="Chọn đồng bộ vào lịch">
              <input type="checkbox" ${isSelected ? 'checked' : ''} data-change="toggle-reminder" data-id="${it.id}">
              <span class="slider"></span>
            </label>
          </div>
        `;
      }).join('');
    }

    async function openNoticeModal(id, type = 'personal') {
      const modal = document.getElementById('noticeDetailModal');
      const titleEl = document.getElementById('modalNoticeTitle');
      const metaEl = document.getElementById('modalNoticeMeta');
      const bodyEl = document.getElementById('modalNoticeBody');

      titleEl.textContent = 'Đang tải thông báo...';
      metaEl.textContent = '';
      bodyEl.innerHTML = '<div style="text-align: center; padding: 40px;"><div class="spinner" style="margin: 0 auto 12px;"></div>Đang kết nối và giải mã nội dung từ HCMUTE...</div>';
      modal.classList.add('open');

      try {
        const res = await apiFetch(`/api/notice-detail?id=${encodeURIComponent(id)}&type=${encodeURIComponent(type)}`);
        let data;
        try {
          data = await res.json();
        } catch(e) {
          titleEl.textContent = 'Máy chủ đang phản hồi chậm';
          bodyEl.innerHTML = '<p>Vui lòng thử lại sau giây lát.</p>';
          return;
        }
        if (!data || !data.success) throw new Error(data?.message || 'Không tìm thấy nội dung thông báo');

        titleEl.textContent = data.subject || 'Chi tiết thông báo';
        metaEl.textContent = `${data.sender || 'HCMUTE'} • ${data.date || ''}`;
        if (window.DOMPurify && data.content_html) {
          const cleanHtml = DOMPurify.sanitize(data.content_html, {
            FORBID_TAGS: ['script', 'iframe', 'style', 'object', 'embed'],
            FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover', 'onfocus', 'onblur', 'style']
          });
          bodyEl.innerHTML = cleanHtml;
          bodyEl.querySelectorAll('a').forEach(a => {
            a.setAttribute('target', '_blank');
            a.setAttribute('rel', 'noopener noreferrer');
          });
        } else {
          bodyEl.innerHTML = data.content_html || '<p>Không có nội dung chi tiết.</p>';
        }
      } catch (err) {
        titleEl.textContent = 'Lỗi hiển thị thông báo';
        bodyEl.innerHTML = `<p style="color: var(--accent);">Không thể tải nội dung: ${escapeHtml(err.message)}</p>`;
      }
    }

    function closeNoticeModal(e) {
      if (e && e.target && e.target !== e.currentTarget && e.target.id !== 'noticeDetailModal') {
        return;
      }
      document.getElementById('noticeDetailModal').classList.remove('open');
    }

    // Close on ESC key
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        document.getElementById('noticeDetailModal').classList.remove('open');
      }
    });

    function toggleReminder(id, isChecked) {
      if (isChecked) {
        appState.selectedReminderIds.add(id);
      } else {
        appState.selectedReminderIds.delete(id);
      }
      updateSelectedCounter();
    }

    function updateSelectedCounter() {
      const count = appState.selectedReminderIds.size;
      document.getElementById('selectedReminderCountText').textContent =
        `Đã chọn ${count} trên tổng số ${appState.considerations.length} nhắc nhở`;
      updateDeadlineCard();
    }

    async function exportCategoryIcs(category) {
      const payload = {
        only_upcoming: category !== 'exams',
        include_classes: category === 'classes',
        include_exams: category === 'exams',
        include_reminders: category === 'reminders',
        selected_reminder_ids: Array.from(appState.selectedReminderIds),
      };

      try {
        const res = await apiFetch('/api/export-ics', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.message || 'Không thể tạo file .ics');
        }

        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;

        let filename = 'UTE-Calendar.ics';
        if (category === 'classes') filename = 'hcmute_tkb.ics';
        else if (category === 'exams') filename = 'hcmute_lich_thi.ics';
        else if (category === 'reminders') filename = 'hcmute_nhac_nho.ics';

        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        showBanner(`Đã tải file ${filename}! Nhấp mở file để import vào Lịch.`, 'success');
      } catch (err) {
        showBanner('Lỗi tải file .ics: ' + err.message, 'error');
      }
    }

    async function downloadCustomIcs() {
      const incClasses = document.getElementById('syncOptClasses')?.checked ?? true;
      const incExams = document.getElementById('syncOptExams')?.checked ?? true;
      const incReminders = document.getElementById('syncOptReminders')?.checked ?? true;

      if (!incClasses && !incExams && !incReminders) {
        showBanner('Vui lòng chọn ít nhất 1 mục để xuất lịch!', 'error');
        return;
      }

      const payload = {
        include_classes: incClasses,
        include_exams: incExams,
        include_reminders: incReminders,
        only_upcoming: !appState.includePastSchedule,
        selected_reminder_ids: Array.from(appState.selectedReminderIds),
      };

      try {
        const res = await apiFetch('/api/export-ics', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.message || 'Không thể tạo file .ics');
        }

        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'UTE-Calendar.ics';
        document.body.appendChild(a);
        a.click();
        a.remove();
        showBanner('Đã tải file lịch theo đúng các mục bạn chọn! Nhấp mở file để import vào Calendar.', 'success');
      } catch (err) {
        showBanner('Lỗi tải file .ics: ' + err.message, 'error');
      }
    }

    let _activeFeedInfo = null;

    function isAppleDevice() {
      return /iPhone|iPad|iPod|Macintosh|Mac OS X/i.test(navigator.userAgent) && !/Android/i.test(navigator.userAgent);
    }

    function updateDeviceSyncButton() {
      const isApple = isAppleDevice();
      const btnApple = document.getElementById('btnAppleCal');
      const btnGoogle = document.getElementById('btnGoogleCal');
      if (btnApple && btnGoogle) {
        if (isApple) {
          btnApple.className = 'btn-primary sync-device-btn';
          btnGoogle.className = 'btn-secondary sync-device-btn';
        } else {
          btnGoogle.className = 'btn-primary sync-device-btn';
          btnApple.className = 'btn-secondary sync-device-btn';
        }
      }
      const btnLegacy = document.getElementById('btnDeviceSync');
      if (btnLegacy) {
        btnLegacy.textContent = isApple ? 'Thêm vào Apple Lịch' : 'Thêm vào Google Lịch';
      }
    }

    async function addToAppleCalendar() {
      const feed = await ensureFeedInfo();
      if (!feed) {
        showBanner('Không thể tải liên kết lịch. Vui lòng đăng nhập lại.', 'error');
        return;
      }
      window.location.href = feed.webcal_url;
    }

    async function addToGoogleCalendar() {
      const feed = await ensureFeedInfo();
      if (!feed) {
        showBanner('Không thể tải liên kết lịch. Vui lòng đăng nhập lại.', 'error');
        return;
      }
      const googleUrl = 'https://calendar.google.com/calendar/u/0/r?cid=' + encodeURIComponent(feed.webcal_url);
      window.open(googleUrl, '_blank', 'noopener');
    }

    async function ensureFeedInfo() {
      if (_activeFeedInfo) return _activeFeedInfo;
      try {
        const res = await apiFetch('/api/calendar/feed-token');
        const data = await res.json();
        if (data && data.success) {
          _activeFeedInfo = data;
          return data;
        }
      } catch (e) {
        console.warn('Lỗi tải thông tin lịch:', e);
      }
      return null;
    }

    function toggleOtherCalendarBox() {
      const box = document.getElementById('otherCalendarBox');
      if (!box) return;
      box.classList.toggle('hidden');
    }

    function toggleAutoSyncGuide() {
      const guide = document.getElementById('autoSyncGuideBox');
      const btn = document.getElementById('btnToggleAutoGuide');
      if (!guide) return;
      const isHidden = guide.classList.toggle('hidden');
      if (btn) {
        btn.textContent = isHidden ? 'Xem cách cài' : 'Đóng hướng dẫn';
      }
    }

    function formatSyncTime(ts) {
      if (!ts) return 'Chưa có thông tin';
      const d = new Date(ts * 1000);
      const h = String(d.getHours()).padStart(2, '0');
      const m = String(d.getMinutes()).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      const month = String(d.getMonth() + 1).padStart(2, '0');
      return `Lấy lúc ${h}:${m} ngày ${day}/${month}`;
    }

    async function loadSyncTabInfo() {
      updateDeviceSyncButton();
      try {
        const feed = await ensureFeedInfo();
        if (!feed) return;
        applyCalendarOptionsToUI(feed.options, feed.calendars);

        const input = document.getElementById('customLiveUrlInput');
        if (input) input.value = feed.webcal_url || feed.feed_url;

        const lastUpdatedEl = document.getElementById('syncLastUpdatedLabel');
        if (lastUpdatedEl) {
          lastUpdatedEl.textContent = feed.updated_at ? formatSyncTime(feed.updated_at) : 'Chưa có thông tin';
        }

        const cardAutoSync = document.getElementById('cardAutoSync');
        if (cardAutoSync) {
          cardAutoSync.classList.remove('hidden');
          const btnGuide = document.getElementById('btnToggleAutoGuide');
          const prepNotice = document.getElementById('autoSyncPrepNotice');
          const guideBox = document.getElementById('autoSyncGuideBox');
          if (feed.auto_sync_template_url && feed.auto_sync_template_url.trim()) {
            if (btnGuide) btnGuide.classList.remove('hidden');
            if (prepNotice) prepNotice.classList.add('hidden');
            const btnCopy = document.getElementById('btnCopySheetLink');
            if (btnCopy) {
              let copyUrl = feed.auto_sync_template_url.trim();
              if (copyUrl.endsWith('/copy')) {
                btnCopy.href = copyUrl;
              } else {
                btnCopy.href = copyUrl.replace(/\/(edit|view|copy)?(\?.*)?$/, '/copy');
              }
            }
          } else {
            if (btnGuide) btnGuide.classList.add('hidden');
            if (guideBox) guideBox.classList.add('hidden');
            if (prepNotice) {
              prepNotice.classList.remove('hidden');
              prepNotice.textContent = 'Tính năng này đang được chuẩn bị.';
            }
          }
        }
      } catch (e) {
        console.warn('Lỗi hiển thị thông tin đồng bộ:', e);
      }
    }

    async function handleMainSyncAction() {
      if (isAppleDevice()) {
        await addToAppleCalendar();
      } else {
        await addToGoogleCalendar();
      }
    }

    async function copyLiveFeedUrl() {
      const feed = await ensureFeedInfo();
      if (!feed) {
        showBanner('Không thể tải liên kết lịch. Vui lòng thử lại.', 'error');
        return;
      }
      const link = feed.webcal_url || feed.feed_url;
      navigator.clipboard.writeText(link).then(() => {
        showBanner('Đã sao chép liên kết vào bộ nhớ tạm.', 'success');
      }).catch(() => {
        prompt('Sao chép liên kết:', link);
      });
    }

    async function refreshCalendarFromSchool() {
      const btn = document.getElementById('btnManualRefresh');
      if (btn) {
        btn.disabled = true;
        btn.textContent = 'Đang lấy...';
      }
      try {
        const res = await apiFetch('/api/calendar/refresh', { method: 'POST' });
        const data = await res.json();
        if (res.status === 429) {
          showBanner(data.message || 'Bạn vừa lấy lịch xong. Hãy thử lại sau ít phút.', 'error');
          return;
        }
        if (data && data.success) {
          if (_activeFeedInfo) {
            _activeFeedInfo.updated_at = data.updated_at;
          }
          const lastUpdatedEl = document.getElementById('syncLastUpdatedLabel');
          if (lastUpdatedEl && data.updated_at) {
            lastUpdatedEl.textContent = formatSyncTime(data.updated_at);
          }
          showBanner('Đã lấy lịch mới. Lịch trong máy có thể đổi sau vài giờ.', 'success');
          loadOverviewData();
        } else {
          showBanner(data.message || 'Không thể lấy lịch từ trường.', 'error');
        }
      } catch (e) {
        showBanner('Lỗi kết nối khi lấy lịch.', 'error');
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = 'Lấy lại lịch mới';
        }
      }
    }

    async function regenerateFeedToken() {
      if (!confirm('Bạn có chắc muốn tạo lại liên kết mới? Liên kết cũ trên ứng dụng Lịch sẽ ngừng hoạt động.')) {
        return;
      }
      try {
        const res = await apiFetch('/api/calendar/feed-token/regenerate', { method: 'POST' });
        const data = await res.json();
        if (data && data.success) {
          _activeFeedInfo = data;
          const input = document.getElementById('customLiveUrlInput');
          if (input) input.value = data.webcal_url || data.feed_url;
          const lastUpdatedEl = document.getElementById('syncLastUpdatedLabel');
          if (lastUpdatedEl && data.updated_at) {
            lastUpdatedEl.textContent = 'Cập nhật lần cuối: ' + formatSyncTime(data.updated_at);
          }
          showBanner('Đã tạo lại liên kết mới.', 'success');
        } else {
          showBanner('Không thể tạo lại liên kết.', 'error');
        }
      } catch (e) {
        showBanner('Lỗi kết nối khi tạo lại liên kết.', 'error');
      }
    }

    async function wipeMyData() {
      if (!confirm('Bạn có chắc muốn xoá toàn bộ dữ liệu của bạn trên trang web? Thao tác này không thể hoàn tác.')) {
        return;
      }
      try {
        const res = await apiFetch('/api/security/wipe-my-data', { method: 'POST' });
        const data = await res.json();
        if (data && data.success) {
          appState.user = null;
          appState.overviewData = null;
          _activeFeedInfo = null;
          showBanner('Đã xoá toàn bộ dữ liệu của bạn.', 'success');
          setTimeout(() => {
            window.location.reload();
          }, 1000);
        } else {
          showBanner(data.message || 'Không thể xoá dữ liệu.', 'error');
        }
      } catch (e) {
        showBanner('Lỗi kết nối khi xoá dữ liệu.', 'error');
      }
    }

    // --- Hạn chót -> lịch (dùng chung biến thể "han-chot" của liên kết lịch) ---
    function deadlineItems() {
      return (appState.considerations || []).filter(i => i && i.deadline_iso && (i.days_left == null || i.days_left >= 0));
    }

    function updateDeadlineCard() {
      const n = deadlineItems().length;
      const status = document.getElementById('deadlineStatus');
      if (status) {
        status.textContent = n > 0
          ? `Hiện có ${n} hạn chót sắp tới trong thông báo của bạn.`
          : 'Chưa có thông báo nào có hạn chót. Khi trường đăng thông báo mới, bạn bấm Quét lại thông báo.';
      }
      ['btnDeadlineGoogle', 'btnDeadlineApple', 'btnDeadlineIcs'].forEach(id => {
        const b = document.getElementById(id);
        if (b) b.disabled = n === 0;
      });
      const apple = isAppleDevice();
      [['btnDeadlineApple', apple], ['btnDeadlineGoogle', !apple]].forEach(([id, primary]) => {
        const b = document.getElementById(id);
        if (!b) return;
        b.classList.remove('btn-primary', 'btn-secondary');
        b.classList.add(primary ? 'btn-primary' : 'btn-secondary');
      });
    }

    async function ensureDeadlineCalendar() {
      const feed = await ensureFeedInfo();
      if (!feed) throw new Error('no-feed');
      let cal = (feed.calendars || []).find(c => c.id === 'han-chot');
      if (cal) return cal;
      const o = feed.options || {};
      const res = await apiFetch('/api/calendar/options', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reminder_min: o.reminder_min !== undefined ? o.reminder_min : 20,
          title_style: o.title_style || 'name',
          split: !!o.split,
          deadlines: true,
        }),
      });
      const data = await res.json();
      if (!data || !data.success) throw new Error('save-failed');
      _activeFeedInfo = { ...feed, options: data.options, calendars: data.calendars };
      cal = (data.calendars || []).find(c => c.id === 'han-chot');
      if (!cal) throw new Error('no-deadline-calendar');
      return cal;
    }

    async function addDeadlineCalendar(kind) {
      try {
        const cal = await ensureDeadlineCalendar();
        if (kind === 'apple') {
          window.location.href = cal.webcal_url;
        } else if (kind === 'google') {
          window.open('https://calendar.google.com/calendar/u/0/r?cid=' + encodeURIComponent(cal.webcal_url), '_blank', 'noopener');
        } else {
          const url = cal.feed_url || new URL(cal.url, window.location.origin).href;
          const res = await fetch(url, { cache: 'no-store' });
          if (!res.ok) throw new Error('download-failed');
          const blob = await res.blob();
          const a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          a.download = 'ute-calendar-han-chot.ics';
          document.body.appendChild(a);
          a.click();
          a.remove();
          setTimeout(() => URL.revokeObjectURL(a.href), 1000);
        }
      } catch (e) {
        showBanner('Chưa thêm được hạn chót vào lịch. Bạn thử lại sau ít phút.', 'error');
      }
    }

    function downloadCustomIcs() {
      // Legacy compatibility
    }

    async function toggleCancelSession(uid, shouldCancel) {
      const endpoint = shouldCancel ? '/api/schedule/cancel' : '/api/schedule/uncancel';
      try {
        const res = await apiFetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ uid: uid })
        });
        let data;
        try {
          data = await res.json();
        } catch(e) {
          showBanner('Máy chủ đang phản hồi chậm. Vui lòng thử lại.', 'error');
          return;
        }
        if (data.success) {
          showBanner(shouldCancel ? 'Đã đánh dấu Giảng viên cho nghỉ buổi học này!' : 'Đã khôi phục buổi học vào thời khóa biểu!', 'success');
          await loadOverviewData();
        }
      } catch (err) {
        showBanner('Lỗi: ' + err.message, 'error');
      }
    }

    async function promptAddMakeupClass() {
      const title = prompt("Nhập Tên môn học báo học bù:");
      if (!title) return;
      const dateStr = prompt("Nhập Ngày học bù (dạng dd/mm/yyyy hoặc dd/mm):", new Date().toLocaleDateString('vi-VN'));
      if (!dateStr) return;
      const timeStr = prompt("Nhập Giờ bắt đầu (ví dụ 07:30 hoặc 13:00):", "07:30");
      if (!timeStr) return;
      const location = prompt("Nhập Phòng học (ví dụ C501, A1-203):", "HCMUTE") || "HCMUTE";

      try {
        const res = await apiFetch('/api/schedule/makeup', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title, date: dateStr, start_time: timeStr, location })
        });
        let data;
        try {
          data = await res.json();
        } catch(e) {
          errorDiv.textContent = 'Máy chủ đang khởi động lại. Vui lòng thử lại sau giây lát.';
          errorDiv.classList.remove('hidden');
          return;
        }
        if (!data.success) throw new Error(data.message);
        showBanner(`Đã thêm buổi học bù môn ${title} vào ngày ${dateStr}! Lịch Google Calendar đã tự động cập nhật.`, 'success');
        await loadOverviewData(true);
      } catch (err) {
        showBanner('Lỗi: ' + err.message, 'error');
      }
    }

    function copyWebcalUrl() {
      copyLiveFeedUrl();
    }

    function showBanner(msg, type = 'success') {
      const successB = document.getElementById('successBanner');
      const errorB = document.getElementById('errorBanner');
      successB.classList.add('hidden');
      errorB.classList.add('hidden');

      if (type === 'success') {
        successB.textContent = msg;
        successB.classList.remove('hidden');
      } else {
        errorB.textContent = msg;
        errorB.classList.remove('hidden');
      }
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    // --- Calendar Options & Split Feeds Management (D2) ---
    let _optSaveTimeout = null;

    function renderSecondaryCalendars(calendars, feedToken) {
      const box = document.getElementById('secondaryCalendarsBox');
      const list = document.getElementById('secondaryCalendarsList');
      if (!box || !list) return;

      if (!calendars || calendars.length <= 1) {
        box.classList.add('hidden');
        list.innerHTML = '';
        return;
      }

      // Secondary calendars are all items except the first (primary) one
      const secondaryCals = calendars.slice(1);
      box.classList.remove('hidden');

      let html = '';
      secondaryCals.forEach(cal => {
        const isApple = isAppleDevice();
        const primaryHref = isApple ? cal.webcal_url : 'https://calendar.google.com/calendar/u/0/r?cid=' + encodeURIComponent(cal.webcal_url);
        const altHref = isApple ? 'https://calendar.google.com/calendar/u/0/r?cid=' + encodeURIComponent(cal.webcal_url) : cal.webcal_url;
        const primaryLabel = isApple ? 'Thêm vào máy' : 'Thêm vào Google Lịch';
        const altLabel = isApple ? 'Google Lịch' : 'Ứng dụng khác';

        html += `
          <div class="secondary-cal-item">
            <div class="d-flex items-center gap-8">
              <span class="cal-dot" style="background-color: ${cal.color || '#0072BC'}; width: 10px; height: 10px; border-radius: 50%; display: inline-block;"></span>
              <span class="font-500">${cal.name}</span>
            </div>
            <div class="d-flex gap-8">
              <a href="${primaryHref}" target="_blank" rel="noopener" class="btn-secondary btn-sm" style="text-decoration: none;">
                ${primaryLabel}
              </a>
              <a href="${altHref}" target="_blank" rel="noopener" class="btn-link text-12 text-muted" style="text-decoration: none; align-self: center;">
                ${altLabel}
              </a>
            </div>
          </div>
        `;
      });
      list.innerHTML = typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(html) : html;
    }

    function applyCalendarOptionsToUI(options, calendars) {
      if (!options) return;

      const optReminder = document.getElementById('optReminderMin');
      if (optReminder && options.reminder_min !== undefined) {
        optReminder.value = String(options.reminder_min);
      }

      const btnName = document.getElementById('btnStyleName');
      const btnCodeName = document.getElementById('btnStyleCodeName');
      if (btnName && btnCodeName) {
        if (options.title_style === 'code_name') {
          btnCodeName.classList.add('active');
          btnName.classList.remove('active');
        } else {
          btnName.classList.add('active');
          btnCodeName.classList.remove('active');
        }
      }

      const optSplit = document.getElementById('optSplit');
      if (optSplit && options.split !== undefined) {
        optSplit.checked = Boolean(options.split);
      }

      const optDeadlines = document.getElementById('optDeadlines');
      if (optDeadlines && options.deadlines !== undefined) {
        optDeadlines.checked = Boolean(options.deadlines);
      }

      // Update primary button texts depending on split mode
      const isSplit = Boolean(options.split);
      const btnApple = document.getElementById('btnAppleCal');
      const btnGoogle = document.getElementById('btnGoogleCal');
      if (btnApple) {
        const spanTitle = btnApple.querySelector('span:first-child');
        if (spanTitle) {
          spanTitle.textContent = isSplit ? 'Thêm Lịch học vào máy' : 'Thêm vào Apple Lịch';
        }
      }
      if (btnGoogle) {
        const spanTitle = btnGoogle.querySelector('span:first-child');
        if (spanTitle) {
          spanTitle.textContent = isSplit ? 'Thêm Lịch học vào Google Lịch' : 'Thêm vào Google Lịch';
        }
      }

      if (_activeFeedInfo) {
        const feedTok = _activeFeedInfo.feed_token;
        const dlLink = document.getElementById('downloadIcsLink');
        if (dlLink && feedTok) {
          dlLink.href = `/calendar/${feedTok}/all.ics?download=1`;
        }
      }

      renderSecondaryCalendars(calendars, _activeFeedInfo ? _activeFeedInfo.feed_token : '');
    }

    function triggerCalendarOptionsSave() {
      if (_optSaveTimeout) clearTimeout(_optSaveTimeout);
      _optSaveTimeout = setTimeout(async () => {
        const optReminder = document.getElementById('optReminderMin');
        const optSplit = document.getElementById('optSplit');
        const optDeadlines = document.getElementById('optDeadlines');
        const activeBtn = document.querySelector('#segTitleStyle .segmented-btn.active');

        const payload = {
          reminder_min: optReminder ? parseInt(optReminder.value, 10) : 20,
          title_style: activeBtn ? activeBtn.dataset.style : 'name',
          split: optSplit ? optSplit.checked : false,
          deadlines: optDeadlines ? optDeadlines.checked : false,
        };

        try {
          const res = await apiFetch('/api/calendar/options', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
          const data = await res.json();
          if (data && data.success) {
            _activeFeedInfo = {
              ..._activeFeedInfo,
              options: data.options,
              calendars: data.calendars,
            };

            const ind = document.getElementById('optSavedIndicator');
            if (ind) {
              ind.classList.remove('hidden');
              setTimeout(() => ind.classList.add('hidden'), 1500);
            }

            applyCalendarOptionsToUI(data.options, data.calendars);
          }
        } catch (err) {
          console.warn('Lỗi khi lưu tuỳ chọn lịch:', err);
        }
      }, 300);
    }

    // --- Centralized Delegated Event Listeners (Strict CSP) ---
    function initCentralizedEventListeners() {
      // 1. Delegated Click Listener
      document.addEventListener('click', (e) => {
        // Modal overlay backdrop clicks
        if (e.target.classList.contains('modal-overlay')) {
          e.target.classList.remove('open');
          return;
        }

        // Action elements
        const actionEl = e.target.closest('[data-action]');
        if (actionEl) {
          const act = actionEl.dataset.action;
          switch (act) {
            case 'switch-tab':
              switchTab(actionEl.dataset.tab);
              break;
            case 'login-mode':
              toggleLoginMode(actionEl.dataset.mode);
              break;
            case 'confirm-logout':
              confirmLogout();
              break;
            case 'execute-logout':
              executeLogout();
              break;
            case 'enter-guest-sync':
              enterGuestSyncMode();
              break;
            case 'exit-guest-sync':
              exitGuestSyncMode();
              break;
            case 'open-security-modal':
              openSecurityModal();
              break;
            case 'close-modal': {
              const modalId = actionEl.dataset.modal;
              if (modalId) {
                const el = document.getElementById(modalId);
                if (el) el.classList.remove('open');
              }
              break;
            }
            case 'add-makeup':
              promptAddMakeupClass();
              break;
            case 'export-ics':
              exportCategoryIcs(actionEl.dataset.category);
              break;
            case 'refresh-schedule':
              loadOverviewData(true);
              break;
            case 'refresh-notices':
              loadConsiderations(true);
              break;
            case 'set-mobile-day':
              setMobileDay(parseInt(actionEl.dataset.day, 10));
              break;
            case 'open-class':
              openClassDetailModal(actionEl.dataset.uid);
              break;
            case 'cancel-session':
              toggleCancelSession(actionEl.dataset.uid, actionEl.dataset.cancel === 'true');
              break;
            case 'open-notice':
              openNoticeModal(actionEl.dataset.id, actionEl.dataset.type || 'general');
              break;
            case 'nav-week':
              navScheduleWeek(parseInt(actionEl.dataset.delta, 10));
              break;
            case 'nav-today':
              navScheduleToday();
              break;
            case 'schedule-view':
              setScheduleViewMode(actionEl.dataset.view);
              break;
            case 'notice-filter':
              setNoticeFilter(actionEl.dataset.filter);
              break;
            case 'download-selected-ics':
              downloadSelectedIcs();
              break;
            case 'deadline-google':
              addDeadlineCalendar('google');
              break;
            case 'deadline-apple':
              addDeadlineCalendar('apple');
              break;
            case 'deadline-ics':
              addDeadlineCalendar('ics');
              break;
            case 'apple-cal':
              addToAppleCalendar();
              break;
            case 'google-cal':
              addToGoogleCalendar();
              break;
            case 'main-sync':
              handleMainSyncAction();
              break;
            case 'toggle-other-cal':
              toggleOtherCalendarBox();
              break;
            case 'copy-live-feed':
              copyLiveFeedUrl();
              break;
            case 'refresh-school':
              refreshCalendarFromSchool();
              break;
            case 'toggle-auto-guide':
              toggleAutoSyncGuide();
              break;
            case 'regen-token':
              regenerateFeedToken();
              break;
            case 'wipe-data':
              wipeMyData();
              break;
          }
          return;
        }

        // Segmented Control for Title Style
        const segBtn = e.target.closest('#segTitleStyle .segmented-btn');
        if (segBtn) {
          document.querySelectorAll('#segTitleStyle .segmented-btn').forEach(b => b.classList.remove('active'));
          segBtn.classList.add('active');
          triggerCalendarOptionsSave();
          return;
        }

        // Bug report link
        const bugLink = e.target.closest('#bugReportLink, .bug-report-link');
        if (bugLink) {
          e.preventDefault();
          fetch('/api/public-config')
            .then(res => res.json())
            .then(cfg => {
              const repo = cfg.repo_url || 'https://github.com/hcmute-calendar/ute-calendar';
              const ver = cfg.version || '1.0.0';
              const ua = navigator.userAgent;
              const title = encodeURIComponent('[Lỗi]: ');
              const body = encodeURIComponent(
                '### Mô tả sự cố\n\n' +
                '### Các bước tái hiện\n1. \n2. \n\n' +
                '### Môi trường\n- Phiên bản UTE-Calendar: ' + ver + '\n' +
                '- Trình duyệt / Thiết bị: ' + ua + '\n' +
                '- Độ phân giải màn hình: ' + window.innerWidth + 'x' + window.innerHeight + '\n\n' +
                '*(Lưu ý: Không gửi MSSV hoặc mật khẩu vào đây)*'
              );
              const issueUrl = repo.replace(/\/+$/, '') + '/issues/new?title=' + title + '&body=' + body;
              window.open(issueUrl, '_blank', 'noopener,noreferrer');
            })
            .catch(() => {});
          return;
        }
      });

      // 2. Form Submissions
      const formPass = document.getElementById('formLoginPass');
      if (formPass) {
        formPass.addEventListener('submit', (e) => {
          e.preventDefault();
          handleLogin(e);
        });
      }
      const formToken = document.getElementById('formLoginToken');
      if (formToken) {
        formToken.addEventListener('submit', (e) => {
          e.preventDefault();
          handleTokenLogin(e);
        });
      }

      // 3. Select & Input Changes
      const yearSelect = document.getElementById('yearSelect');
      const termSelect = document.getElementById('termSelect');
      if (yearSelect) yearSelect.addEventListener('change', onSemesterChange);
      if (termSelect) termSelect.addEventListener('change', onSemesterChange);

      const schToggle = document.getElementById('onlyUpcomingScheduleToggle');
      if (schToggle) schToggle.addEventListener('change', (e) => toggleSchedulePast(e.target.checked));

      const exToggle = document.getElementById('onlyUpcomingExamsToggle');
      if (exToggle) exToggle.addEventListener('change', (e) => toggleExamsPast(e.target.checked));

      document.addEventListener('change', (e) => {
        const t = e.target && e.target.closest ? e.target.closest('[data-change="toggle-reminder"]') : null;
        if (t) toggleReminder(t.dataset.id, t.checked);
      });

      const noticeInput = document.getElementById('noticeSearchInput');
      if (noticeInput) noticeInput.addEventListener('input', (e) => onNoticeSearchChange(e.target.value));

      // Options Accordion inputs
      const optReminder = document.getElementById('optReminderMin');
      if (optReminder) optReminder.addEventListener('change', triggerCalendarOptionsSave);

      const optSplit = document.getElementById('optSplit');
      if (optSplit) optSplit.addEventListener('change', triggerCalendarOptionsSave);

      const optDeadlines = document.getElementById('optDeadlines');
      if (optDeadlines) optDeadlines.addEventListener('change', triggerCalendarOptionsSave);
    }

