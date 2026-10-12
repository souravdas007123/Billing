# Office Billing (Django)

Sirf bill banane ke liye ek simple app. Party select karo, Excel se items paste karo, GST rate chuno, baaki sab auto.

## Pehli baar setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows   (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt

python manage.py makemigrations billing
python manage.py migrate
python manage.py createsuperuser      # ye aapka login hoga
python manage.py runserver
```

Browser me kholein: http://127.0.0.1:8000/

Office ke doosre computers se chalana ho to: `python manage.py runserver 0.0.0.0:8000`
aur wo log `http://<is computer ka IP>:8000/` kholein.

## Ek baar ye bhar lein (Admin: http://127.0.0.1:8000/admin/)

1. **Firm** me apni firm ki details: naam, address, GSTIN, **State**, bank details, terms, invoice prefix.
   State sahi hona zaroori hai: isi se CGST+SGST ya IGST tay hota hai.
2. **Parties** me customers (ya bill banate waqt naya naam likh do, wo apne aap save ho jayega).
3. **Products** (optional): item ka naam likhte hi HSN, unit, rate, GST% khud aa jaate hain.

## Bill kaise banta hai

- **Invoice No** apne aap aata hai (`INV/26-27/0001`, financial year Apr-Mar ke hisaab se). Badalna ho to badal do.
- **Party** chunte hi address, GSTIN, state, phone aa jaata hai. State se Place of Supply set hota hai.
- **Items**: Excel me rows copy karo -> page par kahin bhi Ctrl+V. Pehle "column order" chun lo
  (jaise `Item | Qty | Rate`). Header wali row apne aap skip hoti hai.
- **GST rate**: upar ek baar chuno, sab lines par lag jaata hai. Kisi line ka alag rate ho to us line me badlo.
- **GST Including / Excluding**: ek dropdown se badalte hi poora hisaab badal jaata hai.
- Totals, CGST/SGST/IGST, round-off aur amount in words live dikhte hain.
- **Ctrl+S** = Save & Print. Print page se Ctrl+P karke PDF bhi bana sakte ho.

## Hisaab ke rules (accuracy)

- Final hisaab hamesha server par `billing/calc.py` se hota hai (Decimal me, float kahin nahi). Screen par jo dikhta hai wahi save hota hai.
- Exclusive: GST taxable value par upar se. Inclusive: rate ke andar se GST nikalta hai, line ka total waisa hi rehta hai jaisa rate se bana.
- Har line ka GST alag round hota hai, CGST + SGST hamesha GST ke barabar. Total nearest rupee tak round-off.
- Bill par party ki details ki copy save hoti hai, isliye baad me party badalne se purane bill nahi badalte.
- Galat entry (qty 0, rate khaali, galat GST rate, duplicate invoice no) save hone se pehle rok di jaati hai.
- GSTIN ka checksum check hota hai (sirf chetavni dikhata hai, rokta nahi).

## GST rates badalne ho

`config/settings.py` me `GST_RATES` aur `DEFAULT_GST_RATE`. Jo rates aapka CA bataye wahi rakhein.

## Backup

Saara data `db.sqlite3` file me hai. Roz iski copy kisi doosri jagah rakh lein.

## Tests

```bash
python manage.py test                 # poora
python -m unittest billing.test_calc  # sirf hisaab ke tests (Django ke bina)
```

## Production me chalana ho

`DJANGO_SECRET_KEY` set karein, `DJANGO_DEBUG=0`, `DJANGO_ALLOWED_HOSTS=aapka-ip-ya-domain`,
aur `runserver` ki jagah waitress/gunicorn jaisa server use karein. `DEBUG=0` par admin ke CSS/JS
dikhane ke liye `whitenoise` jaisa static-file setup bhi lagana padega (`python manage.py collectstatic`).
Sirf office LAN ke andar chalana ho to `runserver` kaafi hai.
