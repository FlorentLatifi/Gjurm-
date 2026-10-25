import { Link } from "react-router-dom";

import { formatPercent, formatRelative } from "@/shared/lib/format";

import { type AboutProps, CONTACT_IS_EMAIL, CONTACT_URL } from "./about";

/** The methodology page in Albanian; the English page (Info.tsx) is the same text. Keep them in step. */
export function AboutSq({ topics, status }: AboutProps) {
  return (
    <div className="prose">
      <h1>Metodologjia, burimet dhe kufizimet</h1>
      <p>
        <strong>GJURMË</strong> ndjek çfarë publikojnë mediat shqipfolëse dhe ato të rajonit, i
        grupon artikujt që raportojnë të njëjtën ngjarje në lajme dhe tregon kush e raportoi secilin
        lajm e kush jo — sipas këndvështrimit, rajonit dhe pronësisë së mediave. Lajmet i kthen edhe
        në numra të krahasueshëm: cilat tema mbizotërojnë, kush është në lajme, si ndryshon toni i
        raportimit dhe si dallojnë mediat nga njëra-tjetra.
      </p>

      <h2>1. Mbledhja</h2>
      <ul>
        <li>Lexohen vetëm <strong>burime publike RSS</strong>, çdo 15 minuta, me një identifikim të
          qartë të robotit (user agent). Respektohet <code>robots.txt</code>; mediat që e ndalojnë
          qasjen automatike nuk përfshihen.</li>
        <li>Ruajmë <strong>titullin, lidhjen, kohën e publikimit, kategoritë e burimit</strong> dhe një
          fragment të shkurtër që përdoret vetëm për analizë. Fragmentet nuk shfaqen kurrë dhe
          fshihen pas 90 ditësh. Faqet e artikujve nuk kopjohen kurrë. Një lajm shfaq foton që mediumi e vendos vetë në RSS-in
          e tij, të ngarkuar nga faqja e mediumit dhe me emrin e tij — nuk kopjohet kurrë në serverët
          tanë; një medium mund të kërkojë që fotot e tij të mos shfaqen.</li>
        <li>Dublikatat hiqen (e njëjta lidhje, i njëjti titull i ripublikuar). Titujt pothuajse
          identikë nga media të ndryshme mbahen — raportimi i secilës media llogaritet — dhe lidhen si
          i njëjti lajm.</li>
      </ul>

      <h2 id="analysis">2. Analiza me AI</h2>
      {status && status.analysis.mode !== "ai" && status.analysis.mode !== "none" && (
        <p className="banner" role="note">
          <strong>Mënyra aktuale:</strong>{" "}
          {status.analysis.mode === "rules"
            ? "të gjithë artikujt e fundit u analizuan"
            : `${formatPercent(status.analysis.rule_based_share ?? 0)} e artikujve të fundit u analizuan`}{" "}
          me <em>rregulla fjalësh kyçe</em> në vend të modelit gjuhësor të përshkruar më poshtë: temat
          dhe toni vijnë nga lista fjalësh shqipe, emrat nga fjalët me shkronjë të madhe, dhe nuk ka
          përmbledhje. Kjo është shumë më pak e saktë. Çdo faqe artikulli tregon cila metodë u përdor.
        </p>
      )}
      <ul>
        <li>Çdo titull me fragmentin e tij analizohet nga një model i madh gjuhësor (çdo faqe artikulli
          e emërton modelin), i cili kthen një përshkrim të strukturuar: temën kryesore (nga një listë
          e caktuar me {topics} tema), deri në tri tema dytësore, tonin, llojin e ngjarjes,
          personat, organizatat dhe vendet, shtetet, një përmbledhje njëfjalishe në anglisht dhe një
          vlerësim të sigurisë.</li>
        <li>Rezultati kontrollohet kundrejt një skeme të rreptë. Emrat që nuk gjenden në titull ose në
          fragment hidhen poshtë si shpikje të mundshme. Analizat e dështuara provohen sërish dhe
          regjistrohen; asnjë nuk humbet në heshtje.</li>
        <li><strong>Toni</strong> tregon sa negative ose pozitive është situata e raportuar për publikun
          e gjerë (krimet dhe aksidentet dalin negative; marrëveshjet dhe arritjet pozitive). Nuk
          është gjykim për anshmërinë e medias.</li>
      </ul>

      <h2>3. Si llogariten numrat</h2>
      <ul>
        <li>Ditët janë ditë kalendarike sipas orës së Kosovës dhe Shqipërisë (Europe/Tirane).</li>
        <li><strong>Momenti i temës</strong>: artikujt e 7 ditëve të fundit kundrejt 7 ditëve para
          tyre; rritja = (tani − më parë) / max(më parë, 5).</li>
        <li><strong>Kulmet</strong>: përmendjet e 24 orëve të fundit krahasohen me mesataren dhe
          devijimin standard të përmendjeve ditore të 28 ditëve paraprake (z ≥ 3 dhe të paktën 5
          përmendje).</li>
        <li><strong>Mesataret lëvizëse</strong> janë mesatare të 7 ditëve të fundit.</li>
      </ul>

      <h2 id="stories">4. Lajmet, shiritat e mbulimit dhe pikat e verbra</h2>
      <ul>
        <li>Një <strong>lajm</strong> bashkon artikujt e mediave të ndryshme që raportojnë të njëjtën
          ngjarje, që të shihni kush e raportoi dhe t’i krahasoni titujt e tyre. Titulli, fragmenti
          dhe emrat që gjeti analiza krahasohen si lista fjalësh me pesha (fjalët e rralla, si emrat
          dhe vendet, peshojnë më shumë; mbaresat e fjalëve shqipe barazohen, kështu që “Kurtin” dhe
          “Kurtit” përputhen). Një artikull i bashkohet lajmit më të ngjashëm nëse i gjithë lajmi
          mbetet brenda 48 orëve, nëse titulli i tij ndan me lajmin më shumë se emrin e një personi,
          dhe përveç kur titujt përmendin vende, persona ose numra të ndryshëm — “zjarr në Prizren”
          dhe “zjarr në Gjakovë”, ose “12 të vdekur” dhe “3 të vdekur”, mbeten të ndara.</li>
        <li>Grupimi anon nga mbajtja ndaras: dy ngjarje të ndryshme të bashkuara në një do ta
          paraqitnin gabim mbulimin. Prandaj disa parafrazime të së njëjtës ngjarje dalin si lajme
          të veçanta.</li>
        <li><strong>Shiritat e mbulimit</strong> e numërojnë secilën media një herë për lajm dhe i
          ndajnë sipas këndvështrimit, rajonit (ku e ka selinë), pronësisë ose faktualitetit të
          medias. Titulli që shfaqet për një lajm është ai me formulimin më të afërt me të gjithë të
          tjerët.</li>
        <li><strong>Pikë e verbër</strong>: të paktën 3 media të vlerësuara e raportuan lajmin, 60% ose
          më shumë prej tyre nga njëra anë dhe jo më shumë se 15% nga ana tjetër — ose lajmi ka të bëjë
          me një shtet (të përmendur në të paktën gjysmën e artikujve të analizuar) mediat e të cilit
          nuk e raportuan.</li>
        <li><strong>Raportuar së pari</strong> është media me kohën më të hershme të publikimit ndër
          artikujt e lajmit, sipas burimeve RSS.</li>
        <li><strong>Gjurma</strong> në faqen e lajmit e vizaton çdo raportim si një shenjë në një vijë
          të vetme kohore, me ngjyrën e ndarjes së zgjedhur; raportimi i parë është shenja më e
          lartë.</li>
      </ul>

      <h2 id="ratings">5. Si vlerësohen mediat</h2>
      <ul>
        <li><strong>Këndvështrimi</strong> (majtas · anon majtas · qendër · anon djathtas · djathtas)
          dhe <strong>faktualiteti</strong> (shumë i lartë … shumë i ulët) janë gjykime redaksionale
          për <em>median</em>, kurrë për një artikull të vetëm. GJURMË shfaq vetëm vlerësime që
          mbështeten në një shqyrtim të dokumentuar dhe e tregon bazën e tyre në faqen e medias. Deri
          atëherë media shfaqet <em>pa vlerësim</em> (një segment me viza në çdo shirit).</li>
        <li><strong>Pronësia</strong> (kompani private, grup mediatik, transmetues publik, media
          publike ndërkombëtare, jofitimprurëse …) merret nga informacioni publik për botuesin.</li>
        <li>Ngjyrat ndjekin Ground News — bordo për të majtën, gri e çelët për qendrën, blu e errët për
          të djathtën — që lexuesit e tij t’i lexojnë shiritat menjëherë. Ato janë konventë e shkallës, jo ngjyra
          partiake. Gjetiu në faqe ngjyra del vetëm në grafikë dhe shirita; teksti dhe lidhjet janë
          të zeza.</li>
        <li>Vlerësimet mund të jenë të gabuara ose të vjetruara. Mediat dhe lexuesit mund të kërkojnë
          korrigjim përmes kontaktit më poshtë.</li>
      </ul>

      <h2 id="my-news">6. Anshmëria ime</h2>
      <p>
        Kur hapni një artikull nga GJURMË, ky shfletues shënon median, që faqja{" "}
        <Link to="/my-news">Anshmëria ime</Link> të tregojë balancën e asaj që lexoni. Ky shënim nuk
        largohet kurrë nga shfletuesi juaj (ruhet në hapësirën e tij lokale, jo më shumë se 90 ditë)
        dhe mund ta fshini në atë faqe në çdo kohë.
      </p>

      <h2>7. Kufizimet</h2>
      <ul>
        <li>AI mund t’i klasifikojë gabim temat ose tonin, të bashkojë ose të ndajë emra (“Kurti” dhe
          “Albin Kurti”) dhe të humbasë emra. Etiketat e veçanta janë orientuese; shifrat e
          përgjithshme janë më të besueshme.</li>
        <li>Mbulimi kufizohet te mediat më poshtë dhe te ajo që japin burimet e tyre RSS; mediat që
          publikojnë shumë peshojnë më shumë në totale.</li>
        <li>Burimet ndonjëherë nuk e japin ose e japin gabim kohën e publikimit; këta artikuj
          shënohen “(përafërsisht)”.</li>
      </ul>

      <h2>8. Burimet</h2>
      {status ? (
        <ul>
          {status.sources.map((s) => (
            <li key={s.slug}>{s.name} — {s.is_active ? "aktive" : "nuk mblidhet"}
              {s.last_success_at && <>, lexuar së fundi {formatRelative(s.last_success_at)}</>}</li>
          ))}
        </ul>
      ) : <p>Duke u ngarkuar…</p>}

      <h2 id="contact">9. Korrigjime, kërkesa për heqje dhe privatësia</h2>
      <p>
        Botuesit ose individët mund të kërkojnë korrigjimin ose heqjen e çdo artikulli; ne e fshehim
        atë nga të gjitha faqet dhe statistikat.{" "}
        {CONTACT_IS_EMAIL ? (
          <>Shkruani në <a href={CONTACT_URL}>{CONTACT_URL.slice("mailto:".length)}</a> me lidhjen e artikullit.</>
        ) : (
          <>
            Ju lutemi hapni një kërkesë (issue) në{" "}
            <a href={CONTACT_URL} rel="noopener noreferrer">depon e projektit</a> me lidhjen e
            artikullit (kërkesat janë publike).
          </>
        )}{" "}
        GJURMË nuk përdor cookies, gjurmues apo analitikë; regjistrat e vetë GJURMË-s nuk mbajnë adresa
        IP të plota (ato shkurtohen ose kthehen në kod para se të shkruhen), ndonëse ofruesi i hostimit
        mund t’i mbajë regjistrat e vet të qasjes për pak kohë. Shënimi i leximit për “Anshmëria ime”
        mbetet në shfletuesin tuaj.
      </p>
      <p>
        Për zhvilluesit: të gjitha të dhënat janë të qasshme përmes{" "}
        <a href="/api/docs">API-së publike</a> të dokumentuar.
      </p>
    </div>
  );
}
