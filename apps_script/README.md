# Hướng Dẫn Tạo Bảng Tính Mẫu "UTE-Calendar - Lịch Học Tự Cập Nhật"

> **Dành riêng cho Chủ Dự Án (Project Owner)** để tạo và chia sẻ bảng tính mẫu cho sinh viên.  
> Tài liệu này **không dành cho sinh viên**.

---

## 1. Giới thiệu Kiến Trúc
Sinh viên sẽ bấm **"Tạo bản sao"** (Make a copy) từ đường link mẫu này.  
Khi sinh viên tạo bản sao, toàn bộ mã Apps Script sẽ nằm trong tài khoản Google cá nhân của họ và chạy độc lập:
- Mật khẩu chỉ lưu trong `PropertiesService.getUserProperties()` của tài khoản Google của chính sinh viên đó.
- Chủ dự án và những người khác hoàn toàn không thể xem hoặc truy cập dữ liệu này.

---

## 2. Các Bước Tạo Bảng Mẫu

### Bước 1: Tạo Google Sheets mới
1. Mở trình duyệt và truy cập [sheets.new](https://sheets.new) để tạo một Google Sheet trống.
2. Đổi tên bảng tính thành:  
   **UTE-Calendar - Lịch học tự cập nhật**
3. Đổi tên trang tính đầu tiên thành `Tình trạng`.

### Bước 2: Mở trình chỉnh sửa Apps Script
1. Trên thanh menu của Google Sheets, chọn **Tiện ích mở rộng (Extensions)** &rarr; **Apps Script**.
2. Dự án Apps Script mới sẽ mở ra trong tab mới. Đổi tên dự án thành:  
   `UTE-Calendar Calendar Engine`

### Bước 3: Cấu hình tệp `appsscript.json` (Quyền tối thiểu)
1. Trong giao diện Apps Script, bấm vào biểu tượng bánh răng **Cài đặt dự án (Project Settings)** ở thanh bên trái.
2. Tích chọn ô: **"Hiển thị tệp kê khai 'appsscript.json' trong trình chỉnh sửa" (Show "appsscript.json" manifest file in editor)**.
3. Quay lại mục **Trình chỉnh sửa (Editor)** (biểu tượng `< >`).
4. Mở tệp `appsscript.json`, xoá toàn bộ nội dung cũ và dán nội dung từ tệp [`apps_script/appsscript.json`](./appsscript.json).

### Bước 4: Thêm các tệp mã nguồn
Tạo 3 tệp sau trong Apps Script:

1. **`Logic.gs`**:
   - Bấm dấu `+` cạnh mục Tệp &rarr; Chọn **Tập lệnh (Script)** &rarr; Đặt tên là `Logic`.
   - Dán toàn bộ nội dung từ tệp [`apps_script/Logic.gs`](./Logic.gs).

2. **`Code.gs`**:
   - Mở tệp `Code.gs` có sẵn, dán toàn bộ nội dung từ tệp [`apps_script/Code.gs`](./Code.gs).

3. **`Dialog.html`**:
   - Bấm dấu `+` cạnh mục Tệp &rarr; Chọn **HTML** &rarr; Đặt tên là `Dialog`.
   - Dán toàn bộ nội dung từ tệp [`apps_script/Dialog.html`](./Dialog.html).

4. Bấm biểu tượng đĩa mềm **Lưu dự án (Save project)** (hoặc `Ctrl + S`).

---

## 3. CỰC KỲ QUAN TRỌNG: Cảnh Báo An Toàn
> [!CAUTION]
> **TUYỆT ĐỐI KHÔNG CHẠY "Bật tự động cập nhật" trong bảng mẫu này!**  
> Nếu bạn chạy hoặc nhập tài khoản trong bảng mẫu, dữ liệu và trigger sẽ gắn vào bảng mẫu gốc.  
> Hãy giữ bảng mẫu hoàn toàn trống và sạch sẽ để sinh viên khi copy về sẽ có bản sao độc lập.

---

## 4. Lấy Liên Kết Chia Sẻ "/copy"

1. Quay lại trang Google Sheets gốc.
2. Nhấn nút **Chia sẻ (Share)** ở góc trên bên phải.
3. Ở mục **Quyền truy cập chung (General access)**, đổi thành:  
   **"Bất kỳ ai có đường liên kết" (Anyone with the link)** &rarr; Vai trò: **"Người xem" (Viewer)**.
4. Bấm **Sao chép đường liên kết (Copy link)**.
5. Đường dẫn có dạng:  
   `https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit?usp=sharing`
6. Đổi phần đuôi `/edit...` thành `/copy`:  
   `https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/copy`

---

## 5. Đặt Biến Môi Trường `AUTO_SYNC_TEMPLATE_URL`

1. Đặt liên kết `/copy` vừa tạo vào biến môi trường máy chủ web hoặc tệp `.env`:
   ```bash
   AUTO_SYNC_TEMPLATE_URL="https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/copy"
   ```
2. Nếu triển khai trên Vercel:
   - Vào **Vercel Dashboard** &rarr; Chọn Project &rarr; **Settings** &rarr; **Environment Variables**.
   - Thêm key `AUTO_SYNC_TEMPLATE_URL` với value là đường link `/copy`.
   - Redeploy dự án.

Khi biến môi trường này được cấu hình, trang web UTE-Calendar sẽ tự động hiển thị **Thẻ 2 ("Tự cập nhật khi thầy cô báo nghỉ")** kèm nút tạo bản sao cho sinh viên.

---

## 6. Kiểm Thử Mã Nguồn Logic (Dành Cho Developer)
Mọi hàm tính toán khung giờ, quét thông minh và đồng bộ sự kiện đều được kiểm thử tự động bằng Node.js:
```bash
node apps_script/test_logic.js
```
Kết quả kiểm thử hiển thị chi tiết 17/17 ca kiểm thử thành công.
