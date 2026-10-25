/**
 * UTE-Calendar Static Pages Helper (Hỏi đáp, Bảo mật, Điều khoản)
 * No inline scripts, adheres strictly to Strict Content Security Policy.
 */

document.addEventListener('DOMContentLoaded', function () {
  fetch('/api/public-config')
    .then(function (res) { return res.json(); })
    .then(function (cfg) {
      // 1. Update contact info text if present
      var contactSpan = document.getElementById('contactInfoText');
      if (contactSpan) {
        if (cfg.contact_email) {
          contactSpan.innerHTML = 'Gửi email đến <a href="mailto:' + encodeURIComponent(cfg.contact_email) + '" class="accent-link">' + cfg.contact_email + '</a> kèm mã số sinh viên. Dữ liệu được xoá trong vòng 72 giờ.';
        } else if (cfg.repo_url) {
          contactSpan.innerHTML = 'Mở một Issue trên <a href="' + cfg.repo_url + '" target="_blank" rel="noopener" class="accent-link">GitHub của dự án</a> (đừng đăng mã số sinh viên công khai; hãy dùng nút Xoá dữ liệu của tôi).';
        } else {
          contactSpan.textContent = 'Bạn có thể tự xoá ngay bằng nút Xoá dữ liệu của tôi.';
        }
      }

      var termsSpan = document.getElementById('termsContactText');
      if (termsSpan) {
        if (cfg.contact_email) {
          termsSpan.innerHTML = 'gửi email đến <a href="mailto:' + encodeURIComponent(cfg.contact_email) + '" class="accent-link">' + cfg.contact_email + '</a> kèm mã số sinh viên (xử lý trong vòng 72 giờ).';
        } else if (cfg.repo_url) {
          termsSpan.innerHTML = 'mở Issue trên <a href="' + cfg.repo_url + '" target="_blank" rel="noopener" class="accent-link">GitHub của dự án</a> (đừng đăng mã số sinh viên công khai; hãy dùng nút Xoá dữ liệu của tôi).';
        } else {
          termsSpan.textContent = 'bạn có thể tự xoá ngay bằng nút Xoá dữ liệu của tôi.';
        }
      }

      // 2. Wire up Bug report link
      var bugLinks = document.querySelectorAll('.bug-report-link, #bugReportLink');
      bugLinks.forEach(function (btn) {
        btn.addEventListener('click', function (e) {
          e.preventDefault();
          var repo = cfg.repo_url || 'https://github.com/hcmute-calendar/ute-calendar';
          var ver = cfg.version || '1.0.0';
          var ua = navigator.userAgent;
          var title = encodeURIComponent('[Lỗi]: ');
          var body = encodeURIComponent(
            '### Mô tả sự cố\n\n' +
            '### Các bước tái hiện\n1. \n2. \n\n' +
            '### Môi trường\n- Phiên bản UTE-Calendar: ' + ver + '\n' +
            '- Trình duyệt / Thiết bị: ' + ua + '\n' +
            '- Độ phân giải màn hình: ' + window.innerWidth + 'x' + window.innerHeight + '\n\n' +
            '*(Lưu ý: Không gửi MSSV hoặc mật khẩu vào đây)*'
          );
          var issueUrl = repo.replace(/\/+$/, '') + '/issues/new?title=' + title + '&body=' + body;
          window.open(issueUrl, '_blank', 'noopener,noreferrer');
        });
      });
    })
    .catch(function () {});
});
