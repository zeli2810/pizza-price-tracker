# 🍕 מעקב מחירי פיצה (Pizza Price Tracker)

מערכת שאוספת אוטומטית מדי יום את מחירי הפיצה מ-5 אתרים בישראל, שומרת היסטוריה,
ומציגה דשבורד השוואה באינטרנט.

האתרים: **דומינוס · פיצה האט · פאפא ג'ונס · פייס פלוס · וולט**

לכל רשת נאספים 3 מוצרים להשוואה "תפוח מול תפוח", מעוגנים לכתובת ייחוס בתל אביב:
- **משפחתית** — הפיצה המשפחתית/גדולה הזולה ביותר
- **ארוחת פיצה אחת** — עסקת ארוחה עם פיצה אחת
- **ארוחת שתי פיצות** — עסקת ארוחה עם שתי פיצות

לדומינוס, פיצה האט ופאפא ג'ונס נשמרת הפרדה בין **איסוף** ל**משלוח**;
פייס פלוס ווולט הם מחיר יחיד.

---

## 🏗️ ארכיטקטורה (מודל היברידי)

הסקרייפינג (Playwright + כרום אמיתי) הוא חלק כבד ורגיש, ולכן הוא **רץ על GitHub
Actions** — חינם, אמין, ועם דפדפן אמיתי. Firebase מארח את הדשבורד ושומר את הנתונים:

```
┌─────────────────────┐   scrape יומי 17:00     ┌──────────────────────┐
│   GitHub Actions     │ ──────────────────────▶ │  Firestore (Firebase)│
│  (Playwright scrape)  │   כותב via admin SDK    │   price_history/*     │
│  multi_scraper.py     │                          │   paisplus_offers/*   │
│  paisplus_scraper.py  │                          │   meta/status         │
│  wolt_scraper.py      │                          └──────────┬───────────┘
└─────────────────────┘                                       │ קריאה (public)
          ▲                                                    ▼
          │ repository_dispatch                     ┌──────────────────────┐
   "רענן עכשיו" (אופציונלי, Vercel)                 │  Firebase Hosting     │
          │                                          │  public/index.html    │
          └──────────────────────────────────────── │  (דשבורד + גרפים)     │
                                                     └──────────────────────┘
```

- **Firestore** — מסד הנתונים. כל יום נכתב מסמך `price_history/{תאריך}`, ומסמך
  `meta/status` מתעד הצלחה/כשל אחרון לכל אתר.
- **Firebase Hosting** — מגיש את הדשבורד. הלינק הציבורי הוא כתובת Firebase
  (למשל `https://<project-id>.web.app`). הדשבורד קורא ישירות מ-Firestore.
- **הנתונים נשמרים גם כ-JSON** בתוך הריפו (`data/all_prices.json`) כגיבוי ולפיתוח מקומי.

---

## 📁 מבנה הפרויקט

```
pizza_tracker/
├── multi_scraper.py         # סקרייפר ראשי: דומינוס, פיצה האט, פאפא ג'ונס (+ וולט)
├── wolt_scraper.py          # סקרייפר וולט (מסעדה אחת שנבחרת)
├── paisplus_scraper.py      # סקרייפר פייס פלוס (הצעות)
├── firestore_sync.py        # שכבת כתיבה ל-Firestore (firebase-admin)
├── public/
│   ├── index.html           # הדשבורד (טבלת השוואה + גרפים + סטטוס)
│   └── firebase-config.js   # פרטי ה-Web app של Firebase (למלא!)
├── firebase.json            # הגדרות Hosting + Firestore
├── firestore.rules          # קריאה ציבורית, כתיבה חסומה מהלקוח
├── .firebaserc              # מזהה הפרויקט (למלא!)
├── requirements.txt
├── .github/workflows/
│   ├── scrape.yml           # cron יומי 17:00 + רענון ידני (דומינוס/האט/פאפא + סניפים)
│   ├── scrape_paisplus.yml  # cron יומי 17:00 (פייס פלוס + וולט)
│   └── deploy_firebase.yml  # פריסת הדשבורד ל-Hosting
└── data/                    # גיבוי JSON + צילומי מסך לדיבאג
```

---

## 1️⃣ הרצה מקומית לבדיקה

דרושים Python 3.12+ ו-Node (רק אם רוצים לפרוס ל-Firebase מקומית).

```bash
pip install -r requirements.txt
python -m playwright install chromium chrome

# הרצת הסקרייפר (כותב ל-data/all_prices.json; ל-Firestore רק אם הוגדר secret)
python multi_scraper.py
python paisplus_scraper.py

# תצוגת הדשבורד מקומית (משרת את הריפו ופותח את public/index.html)
python -m http.server 8777
# ואז בדפדפן: http://127.0.0.1:8777/public/index.html
```

בהרצה מקומית ללא הגדרת Firebase, הדשבורד עובר אוטומטית ל**מצב תצוגה מקומי** וקורא
את `data/all_prices.json` — כך אפשר לבדוק הכל בלי ענן.

---

## 2️⃣ הגדרת Firebase (חד-פעמי)

הפרויקט ב-Firebase שלך: **PIZZA TRAKER**.

### א. התקנת הכלים והתחברות
```bash
npm install -g firebase-tools
firebase login
```

### ב. חיבור הריפו לפרויקט
מצא את **Project ID** ב-Firebase Console (⚙️ Project settings → Project ID —
למשל `pizza-traker-1234`), והחלף את הערך ב-`.firebaserc`:
```json
{ "projects": { "default": "מזהה-הפרויקט-שלך" } }
```

### ג. הפעלת Firestore
ב-Console → **Build → Firestore Database → Create database** → בחר
**Production mode** ואזור (למשל `eur3`). כללי האבטחה כבר בקובץ `firestore.rules`
(קריאה ציבורית, כתיבה חסומה מהלקוח).

### ד. יצירת Web app + מילוי `public/firebase-config.js`
ב-Console → Project settings → **Your apps** → הוסף אפליקציית **Web** (`</>`).
העתק את ערכי `firebaseConfig` לתוך `public/firebase-config.js`:
```js
window.FIREBASE_CONFIG = {
  apiKey: "…",
  authDomain: "מזהה-הפרויקט.firebaseapp.com",
  projectId: "מזהה-הפרויקט",
  storageBucket: "מזהה-הפרויקט.appspot.com",
  messagingSenderId: "…",
  appId: "…"
};
window.REFRESH_ENDPOINT = ""; // אופציונלי — ראה סעיף "רענן עכשיו"
```
> ⚠️ ערכי ה-Web config **אינם סוד** — האבטחה מתבצעת דרך `firestore.rules`. מותר לשמור בגיט.

### ה. יצירת Service Account (לכתיבה מ-GitHub Actions)
ב-Console → Project settings → **Service accounts** → **Generate new private key**.
יורד קובץ JSON — זהו סוד! **אין להעלות אותו לגיט** (כבר ב-`.gitignore`).

---

## 3️⃣ הגדרת ה-secrets ב-GitHub

בריפו ב-GitHub → **Settings → Secrets and variables → Actions**:

**Secrets** (מוצפנים):
| שם | ערך |
|----|-----|
| `FIREBASE_SERVICE_ACCOUNT` | **כל תוכן** קובץ ה-JSON של ה-Service Account (הדבק כמו שהוא) |

**Variables** (גלויים):
| שם | ערך |
|----|-----|
| `FIREBASE_PROJECT_ID` | מזהה הפרויקט (למשל `pizza-traker-1234`) |
| `WOLT_VENUE_URL` | קישור לעמוד המסעדה בוולט למעקב (ראה סעיף וולט) |

---

## 4️⃣ פריסה וקבלת לינק ציבורי

פריסה ראשונה מהמחשב:
```bash
firebase deploy --only hosting,firestore:rules
```
בסוף תקבל לינק ציבורי:
```
Hosting URL: https://מזהה-הפרויקט.web.app
```
זהו הלינק היחיד לשיתוף. 🎉

מכאן ואילך, כל `git push` שמשנה את `public/` יפרוס אוטומטית מחדש דרך
`deploy_firebase.yml` (משתמש ב-`FIREBASE_SERVICE_ACCOUNT` ו-`FIREBASE_PROJECT_ID`).

---

## 5️⃣ מעקב וולט — בחירת מסעדה

וולט הוא **אגרגטור**, לא רשת פיצה, ולכן אין "מחיר פיצה של וולט" יחיד. יש לבחור
מסעדה אחת ספציפית בוולט למעקב:

1. היכנס ל-wolt.com, הזן את כתובת הייחוס (תל אביב), ופתח את עמוד המסעדה הרצויה.
2. העתק את כתובת ה-URL (למשל `https://wolt.com/he/isr/tel-aviv/restaurant/<slug>`).
3. הגדר אותה כ-Variable בשם `WOLT_VENUE_URL` ב-GitHub (סעיף 3), או מקומית:
   ```bash
   export WOLT_VENUE_URL="https://wolt.com/he/isr/tel-aviv/restaurant/<slug>"
   python multi_scraper.py
   ```
אם `WOLT_VENUE_URL` ריק — וולט פשוט מדולג ומופיע "אין נתונים" בדשבורד.

> אם וולט מציג עמוד אימות אנושי (Cloudflare/תור), הסקרייפר **מזהה זאת, מתעד
> "האתר חסם גישה אוטומטית — נדרשת בדיקה ידנית", ומדלג — ללא ניסיון עקיפה.**
> שאר האתרים ממשיכים כרגיל.

---

## 6️⃣ אבטחה וכפתור "רענן עכשיו"

- **הדשבורד ציבורי לקריאה** (מחירי פיצה — מידע לא רגיש). כתיבה ל-Firestore חסומה
  לחלוטין מהלקוח (`firestore.rules`); רק הסקרייפר בצד-שרת כותב.
- **"רענן עכשיו"** מפעיל סריקה ידנית. מכיוון שהוא מפעיל פניות יוצאות, הוא מוגן:
  - הכפתור מופיע רק אם הוגדר `window.REFRESH_ENDPOINT` (פונקציית Vercel קטנה
    ששומרת `GITHUB_TOKEN` בצד-שרת ומפעילה את ה-workflow).
  - **מניעת ריצות מקבילות** — `concurrency: pizza-scrape` ב-workflow מבטיח שרק
    ריצה אחת תתבצע בכל רגע; לחיצות נוספות ממתינות/מתבטלות.
  - הכפתור ננעל בזמן ריצה ומציג "רץ…".
- אם אינך רוצה Vercel כלל — השאר את `REFRESH_ENDPOINT` ריק. הכפתור לא יופיע,
  והרענון הידני מתבצע מ-GitHub → Actions → *Daily Pizza Price Scrape* → **Run workflow**.

### להוספת/שינוי הגנת סיסמה על כל הדשבורד
Firebase Hosting לא תומך ב-Basic Auth על תוכן סטטי. אם דרושה סיסמה על הצפייה עצמה,
האפשרות הפשוטה היא Firebase Authentication (Anonymous/Email) + בדיקת התחברות ב-JS,
או שכבת Cloudflare Access לפני ה-Hosting. כרגע המערכת בנויה כדשבורד קריאה-ציבורי.

---

## 7️⃣ בדיקת התזמון וצפייה בלוגים

- **תזמון**: הריצה היומית מוגדרת ב-`.github/workflows/scrape.yml`. cron ב-GitHub הוא
  ב-UTC, ולכן מוגדרים שני טריגרים (14:00 ו-15:00 UTC) וצעד שמדלג על זה שאינו 17:00
  בשעון ישראל — כך רצה בדיוק ריצה אחת ב-17:00 מקומי, גם בקיץ וגם בחורף.
- **צפייה בלוגים**: GitHub → לשונית **Actions** → בחר את ה-workflow → בחר ריצה →
  ראה את פלט השלב *Run scraper* (כולל כמה מחירים נאספו וסטטוס Firestore).
- **בדיקה ידנית מיידית**: Actions → *Daily Pizza Price Scrape* → **Run workflow**.
- **סטטוס בדשבורד**: אזור "סטטוס אתרים" מציג לכל אתר ✅/❌ ומתי הייתה ההצלחה האחרונה
  (מתוך `meta/status`).
- **דיבאג כשל**: בכשל נשמר צילום מסך תחת `data/` (למשל `wolt_blocked.png`).

---

## 🔧 הוספת אתר חדש בעתיד

הקוד מודולרי: הוסף פונקציית `scrape_<name>(...)` שמחזירה
`{"pu": {...}, "dlv": {...}, "error": ...}`, קרא לה ב-`run_scrape` והוסף
`entry["chains"]["<name>"]`, ואז הוסף רשומה למערך `SITES` ב-`public/index.html`.
```
