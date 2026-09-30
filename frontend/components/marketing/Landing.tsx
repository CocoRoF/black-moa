"use client";

import Image from "next/image";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight } from "@/components/icons";
import { LogoMark } from "@/components/brand/Logo";
import { Auth } from "@/lib/api";
import { BRAND } from "@/lib/brand";
import { useLocale, useT } from "@/lib/i18n";
import officePhoto from "@/public/images/landing/secretary-desk.webp";
import styles from "./Landing.module.css";

/** An explicitly labelled example, with no controls that pretend to send a message. */
function ConversationPreview() {
  const t = useT();

  return (
    <aside className={styles.conversation} aria-labelledby="landing-preview-title">
      <div className={styles.conversationHeader}>
        <div className={styles.secretary}>
          <LogoMark size={28} />
          <span id="landing-preview-title">{t("mkt.landing.secretary")}</span>
        </div>
        <span className={styles.exampleLabel}>{t("mkt.landing.example")}</span>
      </div>
      <div className={styles.messages}>
        <p className={styles.question}>
          <span className="sr-only">{t("mkt.landing.visitor")}: </span>
          {t("mkt.landing.question")}
        </p>
        <p className={styles.answer}>
          <span className="sr-only">{t("mkt.landing.secretary")}: </span>
          {t("mkt.landing.answer")}
        </p>
      </div>
    </aside>
  );
}

export function Landing() {
  const t = useT();
  const locale = useLocale();
  const { data } = useQuery({ queryKey: ["auth-status"], queryFn: Auth.status, staleTime: 60_000 });
  const customTagline = data?.tagline && data.tagline !== BRAND.tagline_ko ? data.tagline : null;

  return (
    <div className={styles.landing} lang={locale}>
      {data?.bootstrap_needed ? (
        <div role="status" className={styles.bootstrap}>{t("mkt.bootstrap_banner")}</div>
      ) : null}

      <section className={styles.hero} aria-labelledby="landing-title">
        <div className={styles.intro}>
          <p className={styles.eyebrow}>{t("mkt.landing.eyebrow")}</p>
          <h1 id="landing-title" className={`${styles.title} ${customTagline ? styles.customTitle : ""}`}>
            <span className="sr-only">{BRAND.name} — </span>
            {customTagline || <>
              <span>{t("mkt.landing.title_first")}</span>{" "}
              <span>{t("mkt.landing.title_second")}</span>
            </>}
          </h1>
          <p className={styles.description}>{t("mkt.landing.description")}</p>
          <div className={styles.actions}>
            <Link href="/signup" className={styles.primaryLink}>
              {t("mkt.landing.create")}
              <ArrowUpRight size={20} strokeWidth={1.5} aria-hidden="true" />
            </Link>
            <Link href="/login" className={styles.loginLink}>{t("auth.login")}</Link>
          </div>
        </div>

        <div className={styles.visual}>
          <div className={styles.photograph}>
            <Image
              src={officePhoto}
              alt={t("mkt.landing.photo_alt")}
              fill
              priority
              placeholder="blur"
              sizes="(max-width: 767px) calc(100vw - 40px), (max-width: 1199px) 46vw, 536px"
              className={styles.photo}
            />
          </div>
          <ConversationPreview />
        </div>
      </section>

    </div>
  );
}
