import { Link } from "react-router-dom";

import { useTitle } from "@/shared/hooks/useTitle";
import { getLang, t } from "@/shared/i18n";
import { PREFERENCES_KEY } from "@/stores/preferences";
import { READING_KEY } from "@/stores/reading";

import { ContactLink } from "./Contact";
import { OPERATOR } from "./site";

export function PrivacyPage() {
  useTitle(t("Privacy"), t("What GJURMË keeps about its readers: on the server, in your browser, and at its providers."));
  return getLang() === "sq" ? <PrivacySq /> : <PrivacyEn />;
}

/** The Albanian page; the English one below is the same text. Keep them in step. */
function PrivacySq() {
  return (
    <div className="prose">
      <h1>Privatësia</h1>
      <p>
        GJURMË nuk ka llogari, nuk përdor cookies dhe nuk ka analitikë apo gjurmues. Më poshtë është
        gjithçka që ruhet për lexuesit, në server, në shfletuesin tuaj dhe te ofruesit e hostimit.
      </p>

      <h2 id="server">Çfarë ruhet në server</h2>
      <ul>
        <li>Faqja dërgon te serveri kërkesat që i duhen për të shfaqur lajmet, përfshirë termat që
          kërkoni dhe filtrat që zgjidhni. Serveri i përdor për t’ju përgjigjur; GJURMË nuk i ruan
          në databazë dhe nuk i lidh me ju.</li>
        <li>Adresa IP përdoret vetëm për të kufizuar numrin e kërkesave (mbrojtje nga abuzimi). Ruhet
          në memorien e serverit, e shkurtuar për adresat IPv6, dhe humbet kur instanca e serverit rinis; nuk
          shkruhet në databazë.</li>
        <li>Regjistrat e vetë GJURMË-s shënojnë kërkesat e ngadalta ose të dështuara me rrugën,
          kodin e përgjigjes, kohëzgjatjen dhe një numër kërkese, pa adresë IP dhe pa termat e
          kërkimit. Vetëm në nivelin e detajuar të regjistrimit (që nuk është ai i parazgjedhur) del
          edhe një kod i shkurtër, i hash-uar, në vend të adresës IP.</li>
        <li>Databaza ruan lajmet, artikujt dhe analizat e tyre, jo të dhëna për lexuesit.</li>
      </ul>

      <h2 id="browser">Çfarë ruhet në shfletuesin tuaj</h2>
      <p>
        Në hapësirën lokale të shfletuesit (<code>localStorage</code>), vetëm nga ky shfletues dhe
        asnjëherë të dërguara te serveri:
      </p>
      <ul>
        <li><code>{PREFERENCES_KEY}</code>: tema (e çelët, e errët ose sipas sistemit), ndarja e
          zgjedhur e mbulimit dhe gjuha e faqes.</li>
        <li><code>{READING_KEY}</code>: shënimi i “<Link to="/my-news">Anshmëria ime</Link>”, pra
          mediat e artikujve që hapët këtu, me kohën, lajmin dhe temën; jo më shumë se 500 shënime
          e 90 ditë. E fshini në çdo kohë në atë faqe.</li>
        <li><code>sessionStorage</code> (për një skedë, fshihet kur ajo mbyllet): një vulë kohe që
          e ndalon faqen të rifreskohet pa fund nëse një skedar i saj dështon të ngarkohet.</li>
      </ul>
      <p>
        Mund t’i fshini të gjitha duke pastruar të dhënat e faqes në cilësimet e shfletuesit.
        <strong> Nuk përdoren cookies.</strong>
      </p>

      <h2 id="providers">Ofruesit</h2>
      <ul>
        <li><strong>Vercel</strong> e hoston faqen dhe API-në, dhe <strong>Neon</strong> databazën.
          Si çdo ofrues hostimi, ata mund të mbajnë regjistrat e tyre të qasjes (si adresa IP,
          koha dhe adresa e kërkuar) për një kohë të kufizuar, sipas politikave të tyre.</li>
        <li>Fotot e lajmeve ngarkohen nga serverët e mediave që i botojnë, jo nga ne; media e sheh
          kërkesën e shfletuesit tuaj. Kur hapni një artikull, shkoni te faqja e medias, me
          politikat e saj.</li>
      </ul>

      <h2 id="rights">Të drejtat tuaja dhe kontakti</h2>
      <p>
        GJURMË nuk ruan të dhëna personale të lexuesve në databazën e vet, prandaj nuk ka çfarë t’ju
        dërgojmë ose fshijmë atje; ajo që ruhet në shfletuesin tuaj është nën kontrollin tuaj, siç
        shpjegohet më lart. Për pyetje, kërkesa për qasje, fshirje ose korrigjim, shkruani te{" "}
        <ContactLink lang="sq" />; përgjigjemi brenda {OPERATOR.replyWithin.sq}. Projekti drejtohet nga{" "}
        {OPERATOR.name}, {OPERATOR.place}.
      </p>
      <p>
        Për korrigjimet e artikujve dhe të vlerësimeve të mediave shih <Link to="/who-we-are">Kush jemi</Link>;
        për mënyrën si funksionon faqja, <Link to="/about">metodologjinë</Link>.
      </p>
    </div>
  );
}

function PrivacyEn() {
  return (
    <div className="prose">
      <h1>Privacy</h1>
      <p>
        GJURMË has no accounts, uses no cookies and has no analytics or trackers. Below is everything
        kept about readers: on the server, in your browser and at its hosting providers.
      </p>

      <h2 id="server">What is kept on the server</h2>
      <ul>
        <li>The site sends the server the requests it needs to show the news, including the terms
          you search for and the filters you choose. The server uses them to answer; GJURMË does not
          store them in its database or link them to you.</li>
        <li>The IP address is used only to limit the number of requests (abuse protection). It is
          kept in the server’s memory, shortened for IPv6 addresses, and lost when the server instance
          restarts; it is not written to the database.</li>
        <li>GJURMË’s own logs record slow or failed requests with the path, status code, duration
          and a request number, without an IP address and without search terms. Only at the detailed
          logging level (not the default) is a short hashed code recorded in place of the IP address.</li>
        <li>The database holds the news, articles and their analyses, not data about readers.</li>
      </ul>

      <h2 id="browser">What is kept in your browser</h2>
      <p>
        In the browser’s local storage (<code>localStorage</code>), on this browser only and never
        sent to the server:
      </p>
      <ul>
        <li><code>{PREFERENCES_KEY}</code>: the theme (light, dark or system), the chosen coverage
          split and the site language.</li>
        <li><code>{READING_KEY}</code>: the record behind “<Link to="/my-news">My news bias</Link>”,
          i.e. the outlets of the articles you opened here, with the time, story and topic; at most
          500 entries and 90 days. You can clear it at any time on that page.</li>
        <li><code>sessionStorage</code> (one tab, cleared when it closes): a timestamp that stops the
          page reloading endlessly if one of its files fails to load.</li>
      </ul>
      <p>
        You can remove all of it by clearing the site’s data in your browser settings.
        <strong> No cookies are used.</strong>
      </p>

      <h2 id="providers">Providers</h2>
      <ul>
        <li><strong>Vercel</strong> hosts the site and the API, and <strong>Neon</strong> the
          database. Like any hosting provider, they may keep their own access logs (such as IP
          address, time and requested address) for a limited time, under their own policies.</li>
        <li>Story photos are loaded from the servers of the outlets that publish them, not from ours;
          the outlet sees your browser’s request. When you open an article you go to the outlet’s
          site, under its policies.</li>
      </ul>

      <h2 id="rights">Your rights and contact</h2>
      <p>
        GJURMË keeps no personal data about readers in its own database, so there is nothing there to
        send or delete; what is kept in your browser is under your control, as explained above. For
        questions or requests for access, deletion or correction, write to <ContactLink lang="en" />;
        we answer within {OPERATOR.replyWithin.en}. The project is run by {OPERATOR.name},{" "}
        {OPERATOR.place}.
      </p>
      <p>
        For corrections of articles and outlet ratings see <Link to="/who-we-are">Who we are</Link>; for how the
        site works, the <Link to="/about">methodology</Link>.
      </p>
    </div>
  );
}
