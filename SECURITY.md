# Chính Sách Bảo Mật & Mô Hình Đe Doạ (SECURITY.md)

Tài liệu này mô tả mô hình an toàn thông tin, các biện pháp kỹ thuật phòng thủ và quy trình báo cáo lỗ hổng cho dự án **UTE-Calendar**.

---

## 1. Mô Hình Đe Doạ (Threat Model)

UTE-Calendar được thiết kế xoay quanh nguyên tắc giảm thiểu tối đa bề mặt tấn công và không lưu trữ thông tin nhận dạng nhạy cảm của sinh viên.

| Tác nhân đe doạ / Nguy cơ | Kịch bản tấn công | Biện pháp phòng vệ của UTE-Calendar |
| :--- | :--- | :--- |
| **Lộ mật khẩu sinh viên** | Kẻ tấn công xâm nhập máy chủ hoặc cơ sở dữ liệu để lấy cắp mật khẩu cổng trường | **Máy chủ không lưu mật khẩu.** Khi đăng nhập, mật khẩu chỉ được giữ trong RAM để chuyển tiếp một lần tới cổng trường qua HTTPS rồi huỷ ngay lập tức. Với chế độ tự cập nhật bằng Google Sheets, mật khẩu nằm trong tài khoản Google của chính sinh viên. |
| **Dò quét thời khoá biểu** | Kẻ tấn công quét số thứ tự MSSV để lấy lịch học của người khác | Không sử dụng MSSV trong đường dẫn Lịch. Hệ thống dùng chuỗi ngẫu nhiên 24 bytes URL-safe (`secrets.token_urlsafe(24)`). Sinh viên có thể bấm "Tạo lại liên kết" để đổi chuỗi mới và huỷ chuỗi cũ. |
| **Tấn công dò mật khẩu (Brute-force)** | Kẻ tấn công gửi hàng loạt yêu cầu đăng nhập làm nghẽn hoặc khoá tài khoản | Áp dụng giới hạn tần suất (Rate Limiting): tối đa 5 lần thử trong 10 phút trên mỗi địa chỉ IP và trên mỗi MSSV. |
| **Đánh cắp phiên (Session Hijacking)** | Kẻ tấn công dùng mã độc XSS để đọc cookie phiên | Cookie phiên được đánh dấu `HttpOnly; Secure; SameSite=Lax`. JavaScript không thể truy cập được cookie này. |
| **Chèn mã độc / Clickjacking** | Trang web bị nhúng trong iframe giả mạo hoặc tải script độc hại | Header bảo mật: `Content-Security-Policy: frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. |
| **Làm nghẽn cổng trường (DoS)** | Ứng dụng gửi quá nhiều yêu cầu đồng thời đến hệ thống của trường | Giới hạn tối đa 60 yêu cầu/giờ trên mỗi liên kết lịch; nút "Cập nhật lại từ trường" bị giới hạn tối đa 1 lần mỗi 15 phút cho mỗi sinh viên. |

---

## 2. Các Biện Pháp Bảo Vệ Kỹ Thuật Đã Triển Khai

1. **Không lưu trữ mật khẩu**:
   - Khi sinh viên đăng nhập qua web: mật khẩu chỉ tồn tại trong bộ nhớ RAM trong thời gian thực hiện lệnh gọi HTTPS tới cổng đào tạo trường, sau đó biến `password` được xoá bỏ ngay lập tức bằng `del password`.
   - Khi sử dụng bảng tính Google Sheets: mật khẩu được lưu trong `PropertiesService.getUserProperties()` thuộc tài khoản Google cá nhân của sinh viên, không bao giờ gửi về máy chủ UTE-Calendar.
2. **Bảo vệ Cookie & Phiên làm việc**:
   - Phiên đăng nhập được quản lý bằng cookie `hcmute_session` kèm chữ ký HMAC-SHA256 (`itsdangerous`).
   - Cờ cookie: `HttpOnly` (chống đánh cắp qua XSS), `Secure` (chỉ truyền qua HTTPS), `SameSite=Lax` (chống tấn công CSRF).
3. **Mã ngẫu nhiên thay thế MSSV**:
   - Đường dẫn đăng ký lịch sử dụng dạng `/calendar/<feed_token>/feed.ics`.
   - Nếu sinh viên nghi ngờ lộ liên kết, chỉ cần bấm **"Tạo lại liên kết"**: khóa cũ lập tức bị xoá khỏi bộ nhớ máy chủ và bị vô hiệu hoá (trả về mã 404).
4. **Không ghi nhật ký (Log) thông tin bí mật**:
   - Máy chủ không ghi nhận mật khẩu, token cổng trường hay thông tin điểm số vào log.
   - Thống kê người dùng hàng ngày được ẩn danh hoàn toàn (chỉ tăng bộ đếm lượt truy cập theo ngày).
5. **Quyền được lãng quên (Right to be Forgotten)**:
   - Sinh viên có thể xoá toàn bộ dữ liệu máy chủ bất cứ lúc nào qua nút **"Xoá dữ liệu của tôi"** (`POST /api/security/wipe-my-data`).
   - Toàn bộ nội dung lịch đã lưu, khóa liên kết ngẫu nhiên, phiên làm việc và bộ nhớ tạm sẽ bị xoá vĩnh viễn.

---

## 3. Quy Trình Báo Cáo Lỗ Hổng Bảo Mật

Nếu bạn phát hiện vấn đề bảo mật hoặc lỗ hổng tiềm ẩn trong dự án UTE-Calendar, vui lòng hỗ trợ chúng tôi khắc phục theo quy trình có trách nhiệm:

1. **Kênh tiếp nhận**:
   - Xem mục Liên hệ trên trang /bao-mat hoặc tạo Private Vulnerability Report trên GitHub của dự án.
   - **Vui lòng không công khai lỗ hổng** trên Issue hoặc mạng xã hội trước khi bản vá được phát hành.
2. **Nội dung báo cáo**:
   - Mô tả lỗ hổng và mức độ ảnh hưởng.
   - Các bước cụ thể để tái hiện (Proof of Concept).
   - Đề xuất giải pháp khắc phục (nếu có).
3. **Cam kết phản hồi**:
   - Chúng tôi sẽ phản hồi xác nhận trong vòng **24–48 giờ**.
   - Bản vá sẽ được ưu tiên phát triển, kiểm thử và triển khai trong thời gian sớm nhất có thể.
