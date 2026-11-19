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
        GJURMË nuk ka llogari dhe nuk vendos cookies. Vizitat numërohen me dy shërbime analitike që nuk vendosin cookies në këtë faqe (shih
        më poshtë). Më poshtë është gjithçka që ruhet për lexuesit, në server, në shfletuesin tuaj dhe te ofruesit.
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
        <strong> GJURMË nuk vendos cookies.</strong>
      </p>

      <h2 id="analytics">Analitika</h2>
      <p>Faqja përdor dy shërbime analitike:</p>
      <ul>
        <li><strong>Vercel Web Analytics</strong> numëron faqet e hapura dhe vizitorët, pa cookies dhe,
          sipas përshkrimit të Vercel, pa të dhëna personale, pa profile të lexuesve dhe pa gjurmim mes
          faqesh. Skripta ngarkohet nga i njëjti domen i GJURMË-s (<code>/_vercel/insights/script.js</code>).</li>
        <li><strong>Microsoft Clarity</strong> regjistron si përdoret faqja (klikimet, lëvizjen nëpër
          faqe, lëvizjet e miut dhe faqen ashtu siç e patë), që të shohim ku faqja është e vështirë për
          t’u përdorur: harta nxehtësie dhe regjistrime të vizitave. GJURMË i thotë Clarity-t se
          ruajtja refuzohet, prandaj Clarity nuk vendos cookies në këtë faqe dhe çdo faqe e hapur
          numërohet më vete, pa u lidhur me vizitën tuaj të radhës. Teksti që shkruani, si një kërkim,
          maskohet para se të dalë nga shfletuesi, por Clarity e sheh adresën e faqes, ku mund të jenë
          termat e kërkimit dhe filtrat. Të dhënat shkojnë te Microsoft, që sheh edhe adresën IP dhe
          shfletuesin tuaj, sipas{" "}
          <a href="https://privacy.microsoft.com/privacystatement" rel="noopener noreferrer">deklaratës së privatësisë së Microsoft</a>.
          Serverët e Microsoft-it (<code>clarity.ms</code>) mund të ruajnë cookies të tyre në atë domen,
          në shfletuesit që lejojnë cookies të palëve të treta; Safari i bllokon dhe Firefox i mban të
          ndara për çdo faqe. Skripta ngarkohet nga <code>clarity.ms</code> disa sekonda pasi hapet
          faqja dhe nuk ngarkohet fare nëse shfletuesi juaj dërgon sinjalin <em>Global Privacy
          Control</em> ose <em>Do Not Track</em>.</li>
      </ul>
      <p>Të dyja ekzistojnë vetëm në faqen e hostuar te Vercel. Nuk ka asnjë analitikë tjetër.</p>

      <h2 id="providers">Ofruesit</h2>
      <ul>
        <li><strong>Vercel</strong> e hoston faqen dhe API-në, dhe <strong>Neon</strong> databazën.
          Si çdo ofrues hostimi, ata mund të mbajnë regjistrat e tyre të qasjes (si adresa IP,
          koha dhe adresa e kërkuar) për një kohë të kufizuar, sipas politikave të tyre.</li>
        <li><strong>Microsoft</strong> merr të dhënat e Clarity-t (shih Analitikën më sipër).</li>
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
        GJURMË has no accounts and sets no cookies. Visits are counted by two analytics services that set no cookies on this site (see
        below). Below is everything kept about readers: on the server, in your browser and at its providers.
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
        <strong> GJURMË sets no cookies.</strong>
      </p>

      <h2 id="analytics">Analytics</h2>
      <p>The site uses two analytics services:</p>
      <ul>
        <li><strong>Vercel Web Analytics</strong> counts page views and visitors without cookies and,
          as Vercel describes it, without personal data, reader profiles or cross-site tracking. The
          script is loaded from GJURMË’s own domain (<code>/_vercel/insights/script.js</code>).</li>
        <li><strong>Microsoft Clarity</strong> records how the site is used (clicks, scrolling, mouse
          movement and the page as you saw it), so we can see where it is hard to use: heatmaps and
          recordings of visits. GJURMË tells Clarity that storage is refused, so Clarity sets no
          cookies on this site and counts each page view on its own, not linked to your next visit.
          Text you type, such as a search, is masked before it leaves your browser, but Clarity sees
          the page’s address, which can hold search terms and filters. The data goes to Microsoft,
          which also sees your IP address and browser, under the{" "}
          <a href="https://privacy.microsoft.com/privacystatement" rel="noopener noreferrer">Microsoft privacy statement</a>.
          Microsoft’s servers (<code>clarity.ms</code>) may keep their own cookies on that domain in
          browsers that allow third-party cookies; Safari blocks them and Firefox keeps them separate
          for each site. The script is loaded from <code>clarity.ms</code> a few seconds after the page
          opens, and not at all if your browser sends a <em>Global Privacy Control</em> or{" "}
          <em>Do Not Track</em> signal.</li>
      </ul>
      <p>Both exist only in the site hosted on Vercel. There is no other analytics.</p>

      <h2 id="providers">Providers</h2>
      <ul>
        <li><strong>Vercel</strong> hosts the site and the API, and <strong>Neon</strong> the
          database. Like any hosting provider, they may keep their own access logs (such as IP
          address, time and requested address) for a limited time, under their own policies.</li>
        <li><strong>Microsoft</strong> receives Clarity’s data (see Analytics above).</li>
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
