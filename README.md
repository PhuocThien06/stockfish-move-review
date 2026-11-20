# Stockfish Move Review

Ứng dụng Python chạy trên Windows để tự đi cả hai bên, đánh giá nước vừa đi và xem lại những ván đã kết thúc. Mã nguồn, Stockfish, môi trường Python, PGN và báo cáo đều nằm trong `D:\Chess`.

Đây là ứng dụng độc lập, không liên kết hay được Chess.com bảo trợ. Ứng dụng chỉ dùng [PubAPI công khai](https://support.chess.com/en/articles/9650547-what-is-the-pubapi-and-how-do-i-use-it) để đồng bộ các ván đã kết thúc; không đăng nhập, đọc ván đang diễn ra hay điều khiển bàn cờ trên trang web.

## Cách chạy

1. Cài Python 3.10 trở lên từ [python.org](https://www.python.org/downloads/).
2. Mở PowerShell và cài thư viện trong ổ D:

   ```powershell
   cd D:\Chess
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Tải Stockfish cho Windows từ [trang chính thức](https://stockfishchess.org/download/), giải nén và đặt bản chạy tại `D:\Chess\engine\stockfish.exe`. Stockfish chạy ẩn ở nền. Nếu tệp ở đường dẫn khác, bấm **Chọn tệp…** trong ứng dụng.
4. Nhấp đúp `run.bat`, hoặc chạy:

   ```powershell
   .\.venv\Scripts\python.exe stockfish_review.py
   ```

Tên đồng bộ mặc định là **TheFallenWizard**. Khi mở ứng dụng, chương trình tự lấy các ván công khai đã kết thúc trong 30 ngày gần đây, lưu từng ván một lần vào `D:\Chess\data\games`, rồi mở ván mới nhất. Có thể sửa tên ở thanh trên cùng, bấm **Đồng bộ** hoặc mở **Ván đã lưu**. Việc tải dùng các lời gọi tuần tự tới API; nếu Chess.com giới hạn truy cập, ứng dụng hiển thị lỗi và vẫn dùng được PGN trên máy. Quyền dùng API không bảo đảm tài khoản sẽ không bao giờ bị hạn chế. Theo [Fair Play của Chess.com](https://support.chess.com/en/articles/8568369-what-do-i-need-to-know-about-fair-play-on-chess-com), không dùng Stockfish để phân tích một ván trên Chess.com khi ván đó còn đang diễn ra.

## Sử dụng

- **Bàn cờ tự đi:** bấm quân rồi bấm ô đích, hoặc giữ chuột trái kéo quân và thả. Bạn đi cả Trắng lẫn Đen. Stockfish chỉ đánh giá nước vừa đi và cập nhật thanh lợi thế; không gợi ý nước tiếp theo trong chế độ này.
- **Đánh dấu:** bấm chuột phải lên ô để tô đỏ; giữ chuột phải kéo giữa hai ô để vẽ mũi tên vàng. Có thể vẽ nhiều mũi tên. Bấm lại bằng chuột phải hoặc bấm trái vào ô/mũi tên để xóa.
- **Quân đã ăn và chênh lệch vật chất:** dải trên/dưới bàn cờ hiện quân đối phương mỗi bên đã ăn, số quân đã ăn và điểm hơn `+N` của bên đang dẫn. Điểm quy đổi: tốt 1, mã 3, tượng 3, xe 5, hậu 9. Chỉ số lấy từ vị trí đang hiển thị, nên tua ván, lật bàn hoặc đi nhánh khác sẽ cập nhật ngay; phong cấp cũng được tính vào chênh lệch.
- **PGN riêng:** bấm **Mở PGN…** hoặc **Dán PGN…**. Bản sao được lưu trên ổ D.
- **Tổng quan ván:** khi mở PGN hoặc ván đã lưu, ứng dụng phân tích nền toàn bộ nước đi, hiện bảng phân loại Trắng/Đen và biểu đồ lợi thế. Nút **Xem lại từng nước** sáng lên khi đã chuẩn bị xong điểm cho mọi vị trí, để thanh đánh giá cập nhật ngay lúc chuyển nước.
- **Xem từng nước:** dùng năm nút **đầu / trước / phát tự động / sau / cuối**, các phím `Home`, `←`, `→`, `End`, hoặc bấm nước trong danh sách. Nút **Lật bàn** đổi hướng nhìn.
- **Tạo nhánh khi xem lại:** tại bất kỳ vị trí nào, bấm hoặc kéo quân để thử nước khác. Nếu đi trùng nước PGN thì ứng dụng chuyển tới nước tiếp theo; nếu đi khác, ứng dụng mở nhánh mới và tiếp tục đánh giá từng nước của nhánh. Nhánh được lưu thành PGN riêng trong `D:\Chess\data\games`, có thể mở lại từ **Ván đã lưu**. Bấm **Ván gốc** để quay lại PGN ban đầu; ván gốc không bị ghi đè.
- **Full công suất:** chỉ có khi xem lại; dùng nhiều luồng CPU, thời gian phân tích chọn được, cho biết nước máy ưu tiên và tối đa ba biến thể từ vị trí hiện tại.
- **Hỏi HLV Bruno:** chọn một nước rồi bấm **Hỏi HLV Bruno**. Nhập câu hỏi, ví dụ “Tại sao nước này sai?”, “Nên đi nước nào khác?” hoặc “Có chiến thuật gì?”. Phần giải thích gồm cách chấm điểm, dữ kiện kiểm chứng được trên bàn, nước thay thế và các biến thể theo ký hiệu SAN. Bấm **Đi nước mạnh nhất trên bàn** để quân di chuyển thật từ vị trí trước đó; bấm **Xem tiếp biến thể** để lần lượt đi các nước máy dự kiến. Bruno là hình chibi minh họa, không phải người thật đang trả lời.
- **Yêu thích:** bấm trái tim `♡` cạnh tên ván để chuyển thành `♥`. Các PGN không được yêu thích sẽ bị xóa khi ván/lần lưu đã quá 30 ngày; ván yêu thích được giữ lại. Việc dọn diễn ra lúc khởi động và mỗi ngày nếu ứng dụng mở liên tục. PGN nhiều ván được tách thành từng ván riêng để bạn yêu thích chính xác ván muốn giữ.
- **Thống kê nâng cao:** chấm các nước của một người chơi trong PGN đã mở, tổng hợp phân loại, điểm kỳ vọng mất đi, giai đoạn và màu quân. Báo cáo lưu ở `D:\Chess\data\reports`.

## Cách chương trình giải thích

Stockfish trả về điểm số, xác suất thắng/hòa/thua và các biến thể; bản thân engine không viết lý do bằng tiếng Việt. Ứng dụng chấm mức giảm **điểm kỳ vọng** theo [các ngưỡng Chess.com công bố](https://support.chess.com/en/articles/8572705-how-are-moves-classified-what-is-a-blunder-or-brilliant-etc), rồi tạo lời giải thích từ ba lớp dữ kiện: (1) điểm trước và sau, (2) sự kiện thật trên bàn như chiếu, bắt quân, nhập thành, phong cấp, phát triển quân, (3) biến thể máy tính nếu đi nước khác. Những nhận xét về kế hoạch không được khẳng định nếu không thể chứng minh bằng các nước đi. Các nhãn đặc biệt như *Thiên tài*, *Rất mạnh* và *Bỏ lỡ* là ước lượng; thuật toán chính xác của Chess.com còn dùng quy tắc riêng và Elo. Chạy Full lâu hơn để kiểm tra những vị trí khó.

Kho khai cuộc của ứng dụng được tạo từ [Lichess chess-openings](https://github.com/lichess-org/chess-openings) (CC0); xem `openings/SOURCE.txt`. Phân tích HLV chạy cục bộ, không gửi PGN hay câu hỏi tới dịch vụ AI.

## Dòng lệnh

```powershell
cd D:\Chess
.\.venv\Scripts\python.exe danh_gia_nuoc_di.py "D:\Chess\data\games\van-co.pgn" --stockfish "D:\Chess\engine\stockfish.exe" --player "TheFallenWizard" --csv "ket-qua.csv"
```

PGN, báo cáo và danh sách yêu thích ở `D:\Chess\data`; thư mục này, Stockfish và `.venv` nằm trong `.gitignore`, không được đẩy lên GitHub. Hình quân Neo trong `pieces/` theo mẫu người dùng cung cấp; xem `pieces/ATTRIBUTION.txt`.
