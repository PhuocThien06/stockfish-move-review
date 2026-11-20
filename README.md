# Stockfish Move Review

Ứng dụng Python chạy trên máy để xem lại và đánh giá các ván cờ. Toàn bộ dự án nằm trong `D:\Chess`; PGN và báo cáo nằm trong `D:\Chess\data`. Ứng dụng không đăng nhập, kết nối hoặc tự lấy dữ liệu từ Chess.com.

## Tính năng

- **Bàn cờ thường:** bạn tự đi cả Trắng và Đen bằng cách bấm quân hoặc nhập SAN/UCI. Stockfish chỉ chấm nước vừa đi và cập nhật thanh đánh giá; không đi quân và không hiển thị nước tiếp theo. Ván được tự lưu sau từng nước vào `D:\Chess\data\games`.
- **Dán PGN:** sao chép mã PGN, dán vào ứng dụng; ván được lưu vào `D:\Chess\data\games` rồi mở để xem lại. Cũng có thể mở tệp `.pgn` có sẵn; ứng dụng lưu một bản sao trên ổ D.
- **Xem lại ván:** dùng nút ◀ ▶ hoặc chọn nước trong danh sách.
- **Full công suất:** chỉ bật khi xem lại ván. Hiển thị nước mạnh nhất ở lượt vừa qua, tối đa ba phương án tiếp theo và các dòng biến ngắn. Có thể chọn thời gian phân tích mỗi vị trí.
- **Thống kê nâng cao:** chấm các nước của một người chơi qua những ván PGN đã mở; tổng hợp tỷ lệ nước tốt/sai lầm, độ lệch trung bình, theo giai đoạn và theo màu quân. Báo cáo `.txt` lưu trong `D:\Chess\data\reports`.
- **Dòng lệnh:** `danh_gia_nuoc_di.py` để chấm cả tệp PGN và tùy chọn xuất CSV.

Nhãn *Best Move*, *Tốt*, *Sai lầm*... là ước lượng từ Stockfish trong ứng dụng này, không phải hệ thống phân loại độc quyền của Chess.com. Tăng thời gian phân tích để kết quả ổn định hơn.

## Cài đặt trên Windows

1. Cài Python 3.10 trở lên từ [python.org](https://www.python.org/downloads/).
2. Đặt mã nguồn trong `D:\Chess`. Trong PowerShell, tạo môi trường Python ngay trong dự án và cài thư viện:

   ```powershell
   cd D:\Chess
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Tải Stockfish cho Windows từ [trang chính thức](https://stockfishchess.org/download/), giải nén và đặt bản chạy tại `D:\Chess\engine\stockfish.exe`. Tệp engine được loại khỏi GitHub.
4. Nhấp đúp `run.bat`, hoặc chạy:

   ```powershell
   .\.venv\Scripts\python.exe stockfish_review.py
   ```

5. Nếu engine nằm ở đường dẫn khác, bấm **Chọn tệp…** để chọn `stockfish.exe`.

Để lấy PGN trên Chess.com, mở ván đã chơi, chọn **Share → PGN → Download** hoặc sao chép nội dung PGN rồi dùng **Dán PGN…** trong ứng dụng. [Hướng dẫn Chess.com](https://support.chess.com/en/articles/8705305-how-do-i-get-a-pgn-of-my-game)

## Chấm PGN bằng dòng lệnh

```powershell
.\.venv\Scripts\python.exe danh_gia_nuoc_di.py "D:\Chess\data\games\van-co.pgn" --stockfish "D:\Chess\engine\stockfish.exe" --player "ten-cua-ban" --csv "ket-qua.csv"
```

## Dữ liệu và hình quân

PGN và báo cáo chỉ được lưu trong `D:\Chess\data` trên máy; thư mục này nằm trong `.gitignore` nên không được push lên GitHub. Phân tích Stockfish chạy cục bộ, không có hạn mức ván mỗi ngày từ ứng dụng này.

Bàn cờ dùng tông nâu. Hình quân **Neo** lấy từ [Chess.com](https://www.chess.com/chess-themes/pieces/neo/64/wk.png) theo đúng mẫu người dùng cung cấp. Quyền đối với hình quân thuộc Chess.com; xem `pieces/ATTRIBUTION.txt`.
