# ช่องทาง CSV และการเริ่มหน้า e-GP

ตรวจจาก JavaScript สาธารณะที่หน้าค้นหาใช้อยู่จริงวันที่ 29 ตุลาคม 2569 ไม่ได้สร้างหรือถอดรหัส token และไม่ได้ใช้เซสชันของผู้ใช้

## เส้นทางที่พบ

หน้าค้นหาเป็น shell ที่โหลดโมดูลประกาศแยก ไม่ได้มีฟอร์มอยู่ใน HTML แรก:

1. `/egp-agpc01-web/main.121d82f5c6d6e6bb.js` โหลด bootstrap chunk 744
2. Bootstrap กำหนด route `announcement` ให้โหลด `/egp-aann09-web/remoteEntry.js`
3. Remote ประกาศ exposed module `./Announcement` ซึ่งโหลด `594.f63b663c79b5f1f4.js`

จึงเป็นไปได้ที่ HTTP 200 ของ HTML และภาพพื้นหลังจะสำเร็จ แต่โมดูลประกาศยังไม่เริ่มทำงาน ต้องดูคำขอที่ค้าง/สถานะทรัพยากร/console เพิ่ม ไม่ควรสรุปจากภาพพื้นหลังเพียงอย่างเดียวว่า Cloudflare ปฏิเสธเบราว์เซอร์

## Export CSV ทางการ

`exportExcelCsv` ในโมดูลประกาศส่ง JSON ด้วยวิธี **POST** ไปที่:

`https://process5.gprocurement.go.th/egp-oann10-service/pb/a-egp-allt-project/announcement/csv`

ตัวเว็บใส่ `X-Announcement-Token` ถ้ามีอยู่ในฟอร์ม และตรวจ `validateCfTurnTile` ในคำตอบของ export ด้วย การมีปุ่ม CSV จึงไม่ใช่หลักฐานว่าการส่งออกจากเซิร์ฟเวอร์ใหม่จะไม่ต้องยืนยันตัวตน ต้องทดลองคำขอจริง

คำตอบที่ UI คาดคือ `data.data` เป็น base64 ของ CSV และ `data.size` เป็นจำนวนโครงการ เมื่อ size เท่ากับ 1000 UI แสดงข้อความส่งออกได้เพียง 1000 รายการแรก ตัวทดลองจึงตรวจ base64, CSV header, รูปแบบเลขโครงการ และจำนวนแถวตรงกับ size ก่อนนับว่ารับข้อมูลจริงได้

การทดลองจำกัดด้วย `keywordSearch` เป็นเลขโครงการเดียว `69109071515` ไม่ใช่ส่งออกผลค้นหาทั้งจังหวัด ใช้ปี 2569 จังหวัด 500000 วิธี 16 และประเภท 02 ตามกรณีทดสอบเดิม

## ตัวกรองและข้อมูลกำกับ

ฟังก์ชันสร้าง params รับค่าที่ลงท้ายด้วย `Id` และฟิลด์ที่ระบุไว้ เช่น `budgetYear`, `announceSDate`, `announceEDate`, `projectMoneyS`, `projectMoneyE`, `projectStatus`, `govStatus`, `ministryCode`, `announceType` ช่วงวันที่ถูกแปลงเป็น `YYYY-MM-DD` และยังต้องยืนยันความหมายของวันที่กับ UI ก่อนนำไปแบ่งชุดข้อมูล

Export เพิ่มข้อความกำกับอย่าง `moiName`, `methodName`, `typeName`, `goodsName`, `projectStatusName` แยกจากรหัสตัวกรอง ข้อความในหัว CSV เพียงอย่างเดียวจึงไม่พอพิสูจน์ว่ามีรหัสตัวกรองนั้นส่งไปจริง ตัวอย่างเช่น `goodsName` อาจถูกส่งแม้ไม่มี `goodsId` ต้องเก็บทั้งรหัสที่ใช้ค้นหาและข้อความต้นฉบับใน importer รุ่น production

## แหล่งโค้ดสาธารณะ

- [Shell main](https://process5.gprocurement.go.th/egp-agpc01-web/main.121d82f5c6d6e6bb.js)
- [Announcement remote entry](https://process5.gprocurement.go.th/egp-aann09-web/remoteEntry.js)
- [Announcement module](https://process5.gprocurement.go.th/egp-aann09-web/594.f63b663c79b5f1f4.js)

ไฟล์ต้นทางอาจเปลี่ยนชื่อหลัง e-GP deploy รุ่นใหม่ จึงใช้ URL เหล่านี้เป็นหลักฐาน ณ วันที่ตรวจ ไม่ผูกตัวรับ production กับชื่อ chunk เหล่านี้
