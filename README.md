# UTE-Calendar - Lịch học và lịch thi

Nền tảng hỗ trợ sinh viên Trường Đại học Sư phạm Kỹ thuật TP.HCM (HCMUTE) đưa thời khóa biểu và lịch thi vào ứng dụng Lịch (Apple Calendar, Google Calendar) trên điện thoại và máy tính.

> **Tuyên bố miễn trừ trách nhiệm:**  
> UTE-Calendar là dự án cộng đồng, không do Trường ĐH Sư phạm Kỹ thuật TP.HCM vận hành. Dự án mã nguồn mở, hoạt động phi lợi nhuận. Dự án **hoàn toàn không do Trường Đại học Sư phạm Kỹ thuật TP.HCM (HCMUTE) quản lý, vận hành hay bảo trợ**.

---

## Hai chế độ hoạt động

### 1. Chế độ mặc định (Đường dẫn Lịch)
- **Cách hoạt động:** Sinh viên đăng nhập vào trang web UTE-Calendar một lần để lấy liên kết đăng ký lịch (webcal). Sau đó, bạn chỉ cần bấm **"Thêm vào Lịch của máy"** (iPhone/iPad/Mac) hoặc **"Thêm vào Google Lịch"** (Android/Windows).
- **Cơ chế lưu trữ:**
  - Máy chủ **KHÔNG lưu mật khẩu sinh viên**.
  - Khi sinh viên đăng nhập trên trang web, mật khẩu chỉ được giữ trong bộ nhớ RAM trong vài giây để gửi trực tiếp đến cổng trường qua HTTPS rồi giải phóng ngay lập tức.
  - Máy chủ lưu: nội dung lịch đã dựng sẵn (lịch học + lịch thi), chuỗi khóa ngẫu nhiên trong đường dẫn và phiên đăng nhập tạm thời.
  - Lịch có thể được làm mới khi sinh viên đăng nhập hoặc bấm nút lấy lại lịch mới.

### 2. Chế độ tự cập nhật (Bảng tính Google Sheets)
- **Cách hoạt động:** Dành cho sinh viên muốn lịch tự động thay đổi ngay khi có buổi nghỉ hoặc học bù kể cả khi không mở trang web. Sinh viên tạo một bản sao bảng tính Google Sheets của riêng mình.
- **Cơ chế lưu trữ:**
  - Mật khẩu cổng trường nằm hoàn toàn trong tài khoản Google của chính bạn (`PropertiesService.getUserProperties()` trong Google Apps Script).
  - **Tuyệt đối không gửi mật khẩu đến máy chủ của dự án.**
  - Đoạn mã tự động chạy theo lịch trình thông minh trong tài khoản Google cá nhân của bạn để kiểm tra thay đổi từ trường và cập nhật Google Lịch.

---

## Dữ liệu nào được lưu và không lưu

### Bảng dữ liệu được lưu trên máy chủ (Chế độ mặc định)

| Dữ liệu | Mục đích | Nơi lưu trữ | Thời hạn lưu | Cách xoá |
| :--- | :--- | :--- | :--- | :--- |
| **Nội dung lịch đã dựng** (Lịch học & Lịch thi) | Để ứng dụng Lịch (Apple Calendar, Google Calendar) tải về qua chuẩn iCalendar | Bộ nhớ đệm máy chủ (Upstash Redis hoặc tệp tạm) | Tối đa 150 ngày (một học kỳ) | Bấm nút **"Xoá dữ liệu của tôi"** hoặc khi đăng xuất |
| **Liên kết Lịch ngẫu nhiên** | Chuỗi ngẫu nhiên 24 bytes thay thế MSSV trong đường dẫn (tránh lộ MSSV) | Bộ nhớ máy chủ | Tối đa 150 ngày (một học kỳ) | Bấm **"Tạo lại liên kết"** hoặc **"Xoá dữ liệu của tôi"** |
| **Phiên đăng nhập tạm** | Duy trì trạng thái làm việc trên trình duyệt | Cookie `hcmute_session` (HttpOnly, Secure) | Thời hạn phiên cổng trường (khoảng vài giờ, tối đa 24 giờ) | Bấm **"Đăng xuất"** |

### Những dữ liệu chúng tôi KHÔNG BAO GIỜ lưu
- **Tài khoản quản trị:** Dự án không có tài khoản quản trị và không có trang nào để xem dữ liệu của sinh viên.
- **Mật khẩu sinh viên:** Không lưu trên đĩa cứng, cơ sở dữ liệu hay log máy chủ.
- **Lịch sử truy cập kèm MSSV:** Không theo dõi hành vi truy cập của sinh viên.
- **Địa chỉ IP thô:** Không lưu IP vĩnh viễn gắn liền với MSSV.
- **Điểm số & bảng điểm:** Ứng dụng không đọc hoặc lưu điểm thi, kết quả học tập.
- **Số CCCD / CMND:** Hoàn toàn không thu thập.
- **Tài khoản ngân hàng / Tài chính:** Hoàn toàn không thu thập.

---

## Cách xoá dữ liệu của bạn

Sinh viên có toàn quyền kiểm soát và xoá bỏ thông tin bất cứ lúc nào:
1. **Tự xoá tức thì qua giao diện web:**  
   Vào trang web &rarr; Mục *Cài đặt liên kết* &rarr; Bấm nút **"Xoá dữ liệu của tôi"**.  
   Toàn bộ nội dung lịch, liên kết và phiên làm việc trên máy chủ sẽ bị xoá vĩnh viễn ngay lập tức.
2. **Yêu cầu hỗ trợ xoá thủ công:**  
   Xem mục Liên hệ trên trang /bao-mat (xử lý trong vòng 72 giờ nếu gửi qua email).  
   Đội ngũ hỗ trợ sẽ kiểm tra và xoá sạch toàn bộ dữ liệu liên quan trong vòng **72 giờ**.

---

## Biện pháp an toàn đã triển khai

- **Cookie an toàn:** `HttpOnly`, `Secure`, `SameSite=Lax` chống rò rỉ qua tấn công XSS và CSRF.
- **Tiêu đề bảo mật:** Cấu hình Content Security Policy (CSP), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
- **Giới hạn tần suất (Rate Limiting):**
  - Đăng nhập: Tối đa 5 lần thử trong 10 phút.
  - Tải lịch: Tối đa 60 yêu cầu/giờ trên mỗi liên kết.
  - Làm mới từ trường: Tối đa 1 lần mỗi 15 phút cho mỗi sinh viên.
- **Khóa ngẫu nhiên bí mật:** Liên kết lịch sử dụng token ngẫu nhiên thay vì mã sinh viên.
- **Không log dữ liệu nhạy cảm:** Máy chủ tự động lọc và không in mật khẩu ra log.

Chi tiết mô hình đe doạ và quy trình báo cáo lỗ hổng có tại [SECURITY.md](./SECURITY.md).

---

## Hướng dẫn cài đặt và chạy cục bộ

Nếu muốn tự chạy 100% trên máy tính cá nhân để tự quản lý:

### 1. Yêu cầu môi trường
- Python 3.10 trở lên.
- Đã cài đặt `pip`.

### 2. Cài đặt
```bash
# Nhân bản repository
git clone https://github.com/ngtronghungg/ute-calendar.git
cd ute-calendar

# Tạo môi trường ảo
python -m venv .venv

# Kích hoạt môi trường ảo
# Trên Windows:
.venv\Scripts\activate
# Trên Linux/macOS:
source .venv/bin/activate

# Cài đặt thư viện
pip install -r requirements.txt
```

### 3. Cấu hình tệp `.env`
Sao chép `.env.example` thành `.env` và điền cấu hình:
```env
SESSION_SECRET="chuoi_bi_mat_ngau_nhien_cho_session"

# Tùy chọn triển khai Vercel (Upstash Redis)
# UPSTASH_REDIS_REST_URL="https://...upstash.io"
# UPSTASH_REDIS_REST_TOKEN="..."

# Tùy chọn đường dẫn bảng tính tự cập nhật
# AUTO_SYNC_TEMPLATE_URL="https://docs.google.com/spreadsheets/d/.../copy"
```

### 4. Khởi chạy
```bash
python run.py
```
Mở trình duyệt tại địa chỉ: `http://localhost:5000`.

### 5. Kiểm thử
```bash
# Chạy bộ kiểm thử Python (49 tests)
pytest -q

# Chạy bộ kiểm thử Google Apps Script (17 tests)
node apps_script/test_logic.js
```

---

## Chính sách và điều khoản

- [Chính sách Bảo mật](/bao-mat)
- [Điều khoản Sử dụng](/dieu-khoan)
- [Mô hình An toàn & Báo cáo Lỗ hổng (SECURITY.md)](./SECURITY.md)

---

## Giấy phép
Dự án được phân phối dưới giấy phép **MIT License**.
