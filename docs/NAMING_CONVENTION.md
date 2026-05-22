# Quy uoc dat ten file PDF

De pipeline tu dong nhan dien mon hoc, lop, va tap, dat ten file PDF theo mau sau:

```
<Mon><Lop>_T<Tap>.pdf
```

- `<Mon>`: Ten mon hoc tieng Viet khong dau (vd. `TiengViet`, `Toan`, `Van`, `Su`, `Dia`, `Sinh`)
- `<Lop>`: So lop (vd. `1`, `2`, `6`, `9`, `12`)
- `<Tap>`: So tap (neu sach co nhieu tap) - chi them neu can thiet

## Vi du

| Ten file | Mon | Lop | Tap |
|----------|-----|-----|-----|
| `TiengViet1_T1.pdf` | TiengViet | 1 | 1 |
| `TiengViet1_T2.pdf` | TiengViet | 1 | 2 |
| `Toan3_T1.pdf` | Toan | 3 | 1 |
| `Van8_T2.pdf` | Van | 8 | 2 |
| `Su9.pdf` | Su | 9 | - |

## Quy tac

- Dinh dang: `<Mon><Lop>_T<Tap>` (T = Tap)
- So lop ngay sau ten mon, khong dau cach
- Dau `_` ngăn cach giua phan lop/tap voi ten mon
- `T` viet hoa, followed by so tap
- Khong them so 0 truoc lop/tap (dung `1`, khong `01`)

## Luu y

- Pipeline se lay so dau tien lam grade, so thu hai lam volume/tap.
- Neu chi co 1 so → chi co grade, khong co tap.
- Ten mon phai khop voi thu muc trong `input/` hoac duoc auto-detect tu ten folder.