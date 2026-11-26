"""Step 1: read the raw Akbank export, classify rows, categorise card purchases.

Input : data/raw/hesap_hareketleri.xlsx  (git-ignored)
Output: data/processed/transactions.csv (git-ignored, row level, no person names)

Row types
  purchase  card purchase (description contains the masked card number "XXXX")
  refund    positive card row
  fee       bank fees / taxes on fees (BSMV, KOMISYON, KMV)
  transfer  person-to-person transfers (EFT/FAST/havale). NOT consumption, names dropped.
  cash      ATM withdrawals
  invest    fund purchases, lottery, tax payments etc.
  other
"""
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "hesap_hareketleri.xlsx"
OUT = ROOT / "data" / "processed" / "transactions.csv"

# ordered: first match wins. Patterns run on an UPPER-cased merchant string.
CATEGORY_RULES = [
    ("Food delivery", r"YEMEKSEPETI|GETIR|TRENDYOLYEMEK|MIGROSYEMEK"),
    ("Cafe", r"STARBUCKS|SBX|KAHVE|COFFEE|KOPUKLU|CAFE|KAFE|BISTRO KAHVE"),
    ("Vending", r"OTOMAT|VDL |MATIK"),
    ("Groceries", r"OKUR GRUP|OZGUR SAS|MOPAS|MARKET|MIGROS|A101|\bSOK\b|ŞOK|CARREFOUR|SARKUTERI|TEKEL|TOPTAN VE PERAKENDE|BIM "),
    ("Eating out", r"YUKSELEN YILDIZ|SABANCI UNIVERSITESI|MCDONALD|KEBAPCI|BURGER|CREMMA|BREAD|DURUMLE|DUMPLING|COCO BEACH|TAVERN|RESTAURANT|BALIKCI|KAHVALTI|RESTORAN|PIZZA|SELF GIDA|KUCUK EV|BISTRO|BIG CHEFS|KFC|SIMIT|PACOTTA|TABUFOODS|KAZINTI|HMR|THE CO|NEW CITY|BARU GIDA|BULAD|LOUNGE|UNLU MAMUL|YOMUMU|JOHANNA|BAR\b"),
    ("Transport", r"ISTANBULKART|BELBIM|YANDEX|BITAKSI|PEGASUS|TURIZM|TURI |PETROL|OPET|OTOMOTIV|TOSLA|UBER|MARTI|YAKACIK KART"),
    ("Subscriptions & bills", r"NETFLIX|DISNEY|SPOTIFY|AMAZONPRIME|TCELL|TURKCELL|FATURA|LORKA|YOUTUBE|APPLE|ICLOUD|GOOGLE"),
    ("Online shopping", r"CICEKSEPETI|TRENDYOL|AMAZON|HEPSIBURADA|GRATIS|GRATİS|IYZICO|IYZİCO|PARAM|FITNLIT|PARIBU"),
    ("Travel", r"THY|AJET|GETYOURGUIDE|HALFPRICE|PRAHA|HOTEL|OTEL|CASALINN"),
    ("Official payments", r"HARCLAR|VD MERKEZ|VERGI"),
    ("Clothing & cosmetics", r"OJI STUDIO|MANGO|H AND M|PENTI|JEAN STORE|ZARA|SEPHORA|PULL|BERSHKA|STRADIVARIUS|STRADİVARİUS|KOTON|TOMMY|SUPERSTEP|MARLIN|GIYIM|TEKSTIL|MAGAZACILIK|MAĞAZACILIK|DERI|DERİ|ROSSMANN|NORVCLO|CARMA|HALFPRICE|DEICHMANN|DEİCHMANN|SHOPIER|PAYTR|NKOLAY|QNBPAY|TKPAY"),
    ("Groceries", r"GIDA"),   # generic fallback: any remaining food-company name
    ("Health", r"HASTANE|ECZANE|POLIKLINIK|KLINIK|DOKTOR|OPTIK"),
    ("Entertainment & events", r"SINEMA|MUZE|BILET|BİLET|CINEMA|GOOUT|FOCUS|MENTALIST|TIYATRO"),
]


def classify_type(desc: str, amount: float) -> str:
    d = desc.upper()
    if "XXXX" in d:
        return "purchase" if amount < 0 else "refund"
    if re.search(r"BSMV|KOMİS|KOMIS|-KMV|\bKMV\b|MASRAF|ÜCRET", d):
        return "fee"
    if "ATM" in d or "ÇEKME" in d:
        return "cash"
    if re.search(r"FON ALIMI|PİYANGO|PIYANGO|VERGI|VTA NO", d):
        return "invest"
    if re.search(r"MBL-|FAST|HAV\.|EFT", d):
        return "transfer"
    return "other"


def merchant(desc: str) -> str:
    m = re.sub(r"XXXX\s*\d+", "", desc)
    m = re.sub(r"^\d{3}\s+", "", m)
    m = re.sub(r"\b(TEMASSIZ|3D)\b", "", m)
    return re.sub(r"\s+", " ", m).strip()


def categorise(m: str) -> str:
    u = m.upper().replace("İ", "I").replace("Ş", "S").replace("Ğ", "G").replace("Ü", "U").replace("Ö", "O").replace("Ç", "C")
    for name, pat in CATEGORY_RULES:
        if re.search(pat, u):
            return name
    return "Other"


def main() -> None:
    if not RAW.exists():
        sys.exit(f"Missing {RAW}. See data/raw/README.md")
    df = pd.read_excel(RAW, header=9, engine="calamine")
    df.columns = ["tarih", "saat", "tutar", "bakiye", "aciklama", "fis"]
    df = df.dropna(subset=["tutar"]).copy()
    df["ts"] = pd.to_datetime(
        df["tarih"].astype(str) + " " + df["saat"].astype(str), format="%d.%m.%Y %H:%M", errors="coerce"
    )
    df = df.dropna(subset=["ts"])
    df["type"] = [classify_type(str(a), t) for a, t in zip(df["aciklama"], df["tutar"])]
    df["merchant"] = [merchant(str(a)) if t in ("purchase", "refund") else "" for a, t in zip(df["aciklama"], df["type"])]
    df["category"] = [categorise(m) if t == "purchase" else "" for m, t in zip(df["merchant"], df["type"])]
    df["amount"] = df["tutar"].abs()
    out = df[["ts", "type", "category", "merchant", "tutar"]].sort_values("ts")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    p = out[out["type"] == "purchase"]
    print(f"rows={len(out)}  purchases={len(p)}")
    print(out["type"].value_counts().to_string())
    share = (p["category"] == "Other").mean()
    print(f"uncategorised share (count): {share:.1%}")
    print(p.groupby("category")["tutar"].agg(["size", "sum"]).sort_values("sum").to_string())


if __name__ == "__main__":
    main()
