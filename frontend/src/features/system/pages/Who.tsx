import { Link } from "react-router-dom";

import { useTitle } from "@/shared/hooks/useTitle";
import { getLang, t } from "@/shared/i18n";

import { ContactLink } from "./Contact";
import { OPERATOR } from "./site";

export function WhoPage() {
  useTitle(
    t("Who we are"),
    t("Who runs GJURMË, how it is funded, how outlets can reply and how corrections work."),
  );
  return getLang() === "sq" ? <WhoSq /> : <WhoEn />;
}

/** The Albanian page; the English one below is the same text. Keep them in step. */
function WhoSq() {
  return (
    <div className="prose">
      <h1>Kush jemi</h1>
      <p>
        <strong>GJURMË</strong> grupon lajmet shqip sipas ngjarjeve dhe tregon cilat media e raportuan
        secilën. Kjo faqe thotë kush e drejton, si financohet dhe si korrigjohet.
      </p>

      <h2 id="operator">Kush e drejton</h2>
      <p>
        GJURMË është një projekt personal i drejtuar nga {OPERATOR.name}, me seli në{" "}
        {OPERATOR.place}. Nuk është kompani, redaksi apo organizatë.
      </p>

      <h2 id="funding">Financimi dhe pavarësia</h2>
      <ul>
        <li>Projekt personal, pa financim të jashtëm, pa reklama dhe pa marrëveshje me asnjë media
          apo parti politike.</li>
        <li>Asnjë media dhe asnjë parti nuk ndikon në vlerësimet, në grupimin e lajmeve apo në
          çfarë shfaqet. Mediat shfaqen sipas të njëjtave rregulla, të përshkruara te{" "}
          <Link to="/about">metodologjia</Link>.</li>
      </ul>

      <h2 id="ratings">Vlerësimet e mediave</h2>
      <p>
        Këndvështrimi dhe faktualiteti janë <strong>gjykime redaksionale për median</strong>, jo për
        një artikull të vetëm, dhe mund të jenë të gabuara. Si merren dhe çfarë provash kërkojnë
        është te <Link to="/about#ratings">metodologjia</Link>; çdo media ka në faqen e vet bazën e
        vlerësimit.
      </p>

      <h2 id="reply">E drejta e përgjigjes</h2>
      <p>
        Çdo media që mendon se vlerësimi i saj është i gabuar ose i vjetruar mund të kërkojë
        rishikim: shkruani te <ContactLink lang="sq" /> me emrin e medias dhe provat. Përgjigjemi
        brenda {OPERATOR.replyWithin.sq}. Nëse prova tregojnë gabim, vlerësimi korrigjohet, ose
        media shfaqet pa vlerësim.
      </p>

      <h2 id="corrections">Korrigjime dhe heqje</h2>
      <ul>
        <li>Botuesit dhe individët mund të kërkojnë korrigjimin ose heqjen e një artikulli: e
          fshehim nga të gjitha faqet dhe statistikat. Dërgoni lidhjen e artikullit te{" "}
          <ContactLink lang="sq" />; përgjigjemi brenda {OPERATOR.replyWithin.sq}.</li>
        <li>Një media mund të kërkojë gjithashtu që fotot e saj të mos shfaqen.</li>
      </ul>

      <h2 id="automatic">Çfarë krijohet automatikisht</h2>
      <p className="banner" role="note">
        Përmbledhjet, temat, toni dhe emrat krijohen <strong>automatikisht</strong>, nga një model
        AI ose nga rregulla fjalësh kyçe, dhe <strong>mund të gabojnë</strong>. Grupimi i artikujve
        në lajme është gjithashtu automatik. Lexoni gjithmonë artikullin origjinal para se të
        nxirrni përfundime; çdo artikull këtu lidhet me të.
      </p>

      <p>
        Si funksionon gjithçka: <Link to="/about">metodologjia</Link>. Çfarë ruhet për ju:{" "}
        <Link to="/privacy">privatësia</Link>.
      </p>
    </div>
  );
}

function WhoEn() {
  return (
    <div className="prose">
      <h1>Who we are</h1>
      <p>
        <strong>GJURMË</strong> groups Albanian-language news into stories and shows which outlets
        covered each one. This page says who runs it, how it is funded and how it is corrected.
      </p>

      <h2 id="operator">Who runs it</h2>
      <p>
        GJURMË is a personal project run by {OPERATOR.name}, based in {OPERATOR.place}. It is not a
        company, a newsroom or an organisation.
      </p>

      <h2 id="funding">Funding and independence</h2>
      <ul>
        <li>A personal project: no outside funding, no advertising and no agreement with any
          outlet or political party.</li>
        <li>No outlet and no party influences the ratings, the grouping of stories or what is
          shown. Outlets are treated by the same rules, described in the{" "}
          <Link to="/about">methodology</Link>.</li>
      </ul>

      <h2 id="ratings">Outlet ratings</h2>
      <p>
        Perspective and factuality are <strong>editorial judgements about the outlet</strong>, not
        about a single article, and they can be wrong. How they are reached and what evidence they
        need is in the <Link to="/about#ratings">methodology</Link>; each outlet’s page states the
        basis of its rating.
      </p>

      <h2 id="reply">Right of reply</h2>
      <p>
        Any outlet that thinks its rating is wrong or out of date can ask for a review: write to{" "}
        <ContactLink lang="en" /> with the outlet’s name and your evidence. We answer within{" "}
        {OPERATOR.replyWithin.en}. If the evidence shows an error, the rating is corrected, or the
        outlet is shown unrated.
      </p>

      <h2 id="corrections">Corrections and removal</h2>
      <ul>
        <li>Publishers and individuals can ask for an article to be corrected or removed: we hide
          it from all pages and statistics. Send the article’s link to <ContactLink lang="en" />;
          we answer within {OPERATOR.replyWithin.en}.</li>
        <li>An outlet can also ask for its photos not to be shown.</li>
      </ul>

      <h2 id="automatic">What is generated automatically</h2>
      <p className="banner" role="note">
        Summaries, topics, tone and names are generated <strong>automatically</strong>, by an AI
        model or by keyword rules, and <strong>can be wrong</strong>. Grouping articles into stories
        is automatic too. Always read the original article before drawing conclusions; every
        article here links to it.
      </p>

      <p>
        How everything works: the <Link to="/about">methodology</Link>. What is kept about you:{" "}
        <Link to="/privacy">privacy</Link>.
      </p>
    </div>
  );
}
