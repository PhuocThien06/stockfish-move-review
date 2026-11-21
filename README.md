# Stockfish Move Review

Ứng dụng Python chạy trên Windows để tự đi cả hai bên, đánh giá nước vừa đi và xem lại những ván đã kết thúc. Mã nguồn, Stockfish, môi trường Python, PGN và báo cáo đều nằm trong `D:\Chess`.

Đây là ứng dụng độc lập, không liên kết hay được Chess.com bảo trợ. Ứng dụng dùng [PubAPI công khai](https://support.chess.com/en/articles/9650547-what-is-the-pubapi-and-how-do-i-use-it) để đồng bộ các ván đã kết thúc. Chế độ theo dõi tùy chọn chụp cửa sổ bằng Windows để nhận nước đi đang hiển thị; ứng dụng không đăng nhập, đọc mã trang hay điều khiển bàn cờ trên trang web.

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

Tên đồng bộ mặc định là **TheFallenWizard**. Khi mở ứng dụng hoặc bấm **Đồng bộ**, chương trình lấy tối đa **10 ván công khai đã kết thúc gần nhất trong 30 ngày qua**, lưu mỗi ván một lần vào `D:\Chess\data\games`, rồi mở ván mới nhất. Các ván đã lưu từ lần trước vẫn tuân theo quy tắc dọn sau 30 ngày và ngoại lệ yêu thích. Có thể sửa tên ở thanh trên cùng hoặc mở **Ván đã lưu**. Việc tải dùng các lời gọi tuần tự tới API; nếu Chess.com giới hạn truy cập, ứng dụng hiển thị lỗi và vẫn dùng được PGN trên máy. Quyền dùng API không bảo đảm tài khoản sẽ không bao giờ bị hạn chế. Theo [Fair Play của Chess.com](https://support.chess.com/en/articles/8568369-what-do-i-need-to-know-about-fair-play-on-chess-com), không dùng Stockfish để phân tích một ván trên Chess.com khi ván đó còn đang diễn ra.

## Sử dụng

**Theo dõi trực tiếp:** bấm **Theo dõi bàn cờ trên màn hình…**, chọn cửa sổ và bấm **Chụp cửa sổ**. Kéo chuột khoanh sát 8×8 ô trong ảnh xem trước, chọn **Đen ở dưới** nếu cần. **Lượt hiện tại** mặc định tự suy ra từ hai ô tô màu của nước trước; nếu không suy ra được, chọn Trắng hoặc Đen thủ công. Bấm **Bắt đầu theo dõi**. Ứng dụng tự loại bớt viền mỏng nếu vùng khoanh dính viền bàn cờ và chờ ảnh ngừng thay đổi trước khi ghi nước, tránh nhận nhầm quân đang di chuyển giữa các ô. Có thể bắt đầu từ giữa ván; PGN mới sẽ ghi vị trí đang chụp làm vị trí đầu, nên không chứa các nước đã đi trước khi bắt đầu. Bàn cờ và đánh giá cập nhật sau từng nước được nhận. Bấm **Dừng theo dõi** để ngừng. PGN được lưu sau từng nước trên ổ D; ứng dụng không lưu video liên tục. Ảnh được xử lý theo thứ tự và có thể khôi phục hai nước xảy ra giữa hai lần chụp. Nếu cửa sổ đổi kích thước hoặc bàn cờ xoay, hãy chọn lại vùng. Nếu không nhận được nước hợp lệ sau khi ảnh đổi, chương trình dừng để tránh ghi PGN sai. Chức năng này chỉ chạy trên Windows và dùng Windows Graphics Capture cùng Pillow. Theo Fair Play của Chess.com, chỉ dùng đánh giá trực tiếp khi đấu với bot hoặc luyện tập riêng; ván với người thật chỉ xem lại sau khi kết thúc.

Ảnh xem trước được nén vùng sáng để bớt chói; việc nhận quân tự điều chỉnh theo màu ô trong ảnh chụp, kể cả khi ảnh HDR bị bạc màu. Ứng dụng không thay đổi cài đặt HDR của Windows. Khi phân tích, thanh lợi thế hiện điểm sơ bộ trước; nhãn nước đi xuất hiện sau lượt kiểm tra đầy đủ. Nếu bạn đi tiếp ngay, phép tính cũ được dừng để ưu tiên vị trí mới.

- **Bàn cờ tự đi:** bấm quân rồi bấm ô đích, hoặc giữ chuột trái kéo quân và thả. Bạn đi cả Trắng lẫn Đen. Stockfish chỉ đánh giá nước vừa đi và cập nhật thanh lợi thế; không gợi ý nước tiếp theo trong chế độ này. Thanh giữ mức cũ trong khi Stockfish tính và chuyển mượt khi có điểm mới. Có thể dùng nút đầu/trước/sau/cuối, phím `Home`, `←`, `→`, `End` hoặc danh sách nước để quay lại khi đang tự đi. Nếu đi trùng nước cũ, ứng dụng tiến tới nước đó; nếu đổi nước, ứng dụng lưu đường mới thành PGN riêng và giữ PGN cũ trong **Ván đã lưu**.
- **Đánh dấu:** bấm chuột phải lên ô để tô đỏ; giữ chuột phải kéo giữa hai ô để vẽ mũi tên vàng. Mũi tên từ quân mã đi theo hai đoạn vuông góc; đường chéo từ tượng, hậu và các ô khác đi thẳng đến ô đích. Có thể vẽ nhiều mũi tên. Bấm lại bằng chuột phải hoặc bấm trái vào ô/mũi tên để xóa.
- **Quân đã ăn và chênh lệch vật chất:** dải trên/dưới bàn cờ hiện quân đối phương mỗi bên đã ăn, số quân đã ăn và điểm hơn `+N` của bên đang dẫn. Điểm quy đổi: tốt 1, mã 3, tượng 3, xe 5, hậu 9. Chỉ số lấy từ vị trí đang hiển thị, nên tua ván, lật bàn hoặc đi nhánh khác sẽ cập nhật ngay; phong cấp cũng được tính vào chênh lệch.
- **PGN riêng:** bấm **Mở PGN…** hoặc **Dán PGN…**. Bản sao được lưu trên ổ D.
- **Tổng quan ván:** khi mở PGN hoặc ván đã lưu, ứng dụng phân tích nền toàn bộ nước đi, hiện bảng phân loại Trắng/Đen và biểu đồ lợi thế. Nếu tên của bạn nằm ở bên Đen, bàn cờ mặc định lật để bạn ở dưới; số đánh giá lấy theo bên dưới bàn, nên âm khi bên đó bất lợi. Nút **Xem lại từng nước** sáng lên khi đã chuẩn bị xong điểm cho mọi vị trí, để thanh đánh giá cập nhật ngay lúc chuyển nước.
- **Xem từng nước:** dùng năm nút **đầu / trước / phát tự động / sau / cuối**, các phím `Home`, `←`, `→`, `End`, hoặc bấm nước trong danh sách. Mũi tên vàng cho biết nước mạnh nhất từ vị trí đang xem và được tính lại nếu bạn đi theo. Nút **Lật bàn** đổi hướng nhìn của cả bàn cờ lẫn thanh đánh giá.
- **Tạo nhánh khi xem lại:** tại bất kỳ vị trí nào, bấm hoặc kéo quân để thử nước khác. Nếu đi trùng nước PGN thì ứng dụng chuyển tới nước tiếp theo; nếu đi khác, ứng dụng mở nhánh mới và tiếp tục đánh giá từng nước của nhánh. Nhánh được lưu thành PGN riêng trong `D:\Chess\data\games`, có thể mở lại từ **Ván đã lưu**. Bấm **Ván gốc** để quay lại PGN ban đầu; ván gốc không bị ghi đè.
- **Full công suất:** chỉ có khi xem lại; dùng nhiều luồng CPU, thời gian phân tích chọn được, cho biết nước máy ưu tiên và tối đa ba biến thể từ vị trí hiện tại.
- **Hỏi HLV Bruno:** khi xem lại, Bruno chiếm vùng chính bên phải bàn cờ; danh sách nước và đánh giá nằm trong cột nhỏ ở góc trên phải. Chọn một nước để mở phần hỏi Bruno, hoặc bấm **Hỏi HLV Bruno** để đổi sang nước đang xem. Biểu cảm Bruno đổi theo nhãn nước đi. Nhập câu hỏi rồi bấm **Giải thích**: chương trình nêu dữ kiện cụ thể của vị trí và tự đi biến thể dự kiến trên bàn. Bạn có thể tự đi quân để dừng minh họa. Bấm **Đi nước mạnh nhất trên bàn** để thử phương án khác, rồi **Xem tiếp biến thể** để đi từng nước máy dự kiến. Nếu biến thể khác PGN gốc, ứng dụng lưu nhánh riêng. Bruno là hình minh họa; lời giải thích được tạo trên máy từ bàn cờ và Stockfish, không phải người thật đang trả lời.
- **Yêu thích:** bấm trái tim `♡` cạnh tên ván để chuyển thành `♥`. Các PGN không được yêu thích sẽ bị xóa khi ván/lần lưu đã quá 30 ngày; ván yêu thích được giữ lại. Việc dọn diễn ra lúc khởi động và mỗi ngày nếu ứng dụng mở liên tục. PGN nhiều ván được tách thành từng ván riêng để bạn yêu thích chính xác ván muốn giữ.
- **Thống kê nâng cao:** chấm các nước của một người chơi trong PGN đã mở, tổng hợp phân loại, điểm kỳ vọng mất đi, giai đoạn và màu quân. Báo cáo lưu ở `D:\Chess\data\reports`.

## Cách chương trình giải thích

Stockfish trả về điểm số và các biến thể; bản thân engine không viết lý do bằng tiếng Việt. Ứng dụng chuyển điểm số thành tỷ lệ thắng theo [mô hình Lichess dựa trên dữ liệu ván người chơi](https://lichess.org/page/accuracy), rồi áp [các ngưỡng Chess.com công bố](https://support.chess.com/en/articles/8572705-how-are-moves-classified-what-is-a-blunder-or-brilliant-etc) cho mức giảm **điểm kỳ vọng**. Nhãn *Thiên tài* còn yêu cầu biến thể thể hiện mất vật chất thực sự sau khi đối phương nhận quân và người chơi đáp lại; đổi quân ngang giá không được tính là thí quân. Bruno nêu nước bắt, nước đáp và phần vật chất còn thiếu, kèm đòn chiếu hoặc bắt quân nếu có. Lời giải thích dùng ba lớp dữ kiện: (1) điểm trước và sau, (2) sự kiện thật trên bàn như chiếu, bắt quân, nhập thành, phong cấp, phát triển quân, (3) biến thể máy tính nếu đi nước khác. Những nhận xét về kế hoạch không được khẳng định nếu không thể chứng minh bằng các nước đi. Các nhãn vẫn là ước lượng vì Chess.com dùng mô hình phụ thuộc Elo và quy tắc riêng, đặc biệt cho *Thiên tài*, *Rất mạnh* và *Bỏ lỡ*. Tổng quan dùng 0,45 giây cho lượt đầu và kiểm tra lại nhãn *Sai lầm nghiêm trọng* trong 1,5 giây, nhãn *Thiên tài* trong 2 giây; đánh giá từng nước dùng 1 giây, Full mặc định 3 giây/vị trí và có thể chọn đến 10 giây. Chạy Full lâu hơn để kiểm tra những vị trí khó.

Kho khai cuộc của ứng dụng được tạo từ [Lichess chess-openings](https://github.com/lichess-org/chess-openings) (CC0); xem `openings/SOURCE.txt`. Phân tích HLV chạy cục bộ, không gửi PGN hay câu hỏi tới dịch vụ AI.

## Dòng lệnh

```powershell
cd D:\Chess
.\.venv\Scripts\python.exe danh_gia_nuoc_di.py "D:\Chess\data\games\van-co.pgn" --stockfish "D:\Chess\engine\stockfish.exe" --player "TheFallenWizard" --csv "ket-qua.csv"
```

PGN, báo cáo và danh sách yêu thích ở `D:\Chess\data`; thư mục này, Stockfish và `.venv` nằm trong `.gitignore`, không được đẩy lên GitHub. Hình quân Neo trong `pieces/` theo mẫu người dùng cung cấp; xem `pieces/ATTRIBUTION.txt`.
