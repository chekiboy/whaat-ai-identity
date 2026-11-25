import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { Fragment, useEffect, useState } from "react";
import type { CreatedIdentity } from "@/client";
import {
  createIdentityMutation,
  listIdentitiesQueryKey,
  regenerateTokenMutation,
} from "@/client/@tanstack/react-query.gen";
import { CreateIdentity, TokenOnce } from "@/components/identities/create-identity";
import { ModuleBar, ModuleBarSection } from "@/components/shell/module-bar";
import { LANGUAGES, useLanguage, useTranslation } from "@/i18n";
import { sectionTitle, usePageHeading } from "@/lib/breadcrumb";
import { useIdentitySummaries, useMemoryCounts } from "@/lib/identities";
import { usePersona } from "@/lib/persona";
import { usePreferences } from "@/lib/preferences";
import "@/styles/overview.css";

export const Route = createFileRoute("/settings")({
  component: Settings,
});

const SECTIONS = [
  ["st-identities", "identities"],
  ["st-general", "general"],
] as const;

/* The app's settings in one place, kept in the instance's preferences file: the language, the identity the app opens
   with, and each identity's agent config folder. */
function Settings() {
  const { t } = useTranslation();
  usePageHeading(sectionTitle("Settings"), [{ label: t("settings.title") }]);
  const { language, setLanguage } = useLanguage();
  return (
    <div className="sh-view st">
      <ModuleBar>
        <ModuleBarSection title={t("settings.title")}>
          {SECTIONS.map(([id, key]) => (
            <button
              type="button"
              key={id}
              className="sh-item"
              onClick={() => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" })}
            >
              {t(`settings.${key}`)}
            </button>
          ))}
        </ModuleBarSection>
      </ModuleBar>
      <div className="sh-tb">
        <h1>{t("settings.title")}</h1>
      </div>
      <div className="sh-pane st-pane">
        <Identities />
        <h2 className="st-h" id="st-general">
          {t("settings.general")}
        </h2>
        <section className="st-row">
          <div className="st-label">
            <b>{t("settings.language")}</b>
            <p>{t("settings.languageNote")}</p>
          </div>
          <div className="st-choices">
            {LANGUAGES.map((code) => (
              <button
                type="button"
                key={code}
                className={`st-choice${code === language ? " on" : ""}`}
                onClick={() => setLanguage(code)}
              >
                {t(`languages.${code}`)}
              </button>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

/* Who whaat works with: the identity the app opens with, the identities with their folder and token,
   and adding one; the only place an identity is created. */
function Identities() {
  const { t } = useTranslation();
  const { preferences, update } = usePreferences();
  const identities = useIdentitySummaries() ?? [];
  const counts = useMemoryCounts();
  const { persona } = usePersona();
  const openWith = preferences?.identity?.open_with ?? "last";
  const queryClient = useQueryClient();
  const [issued, setIssued] = useState<{ token: CreatedIdentity; regenerated: boolean } | null>(null);
  const done = (regenerated: boolean) => async (token: CreatedIdentity) => {
    setIssued({ token, regenerated });
    await queryClient.invalidateQueries({ queryKey: listIdentitiesQueryKey() });
  };
  const regenerate = useMutation({ ...regenerateTokenMutation(), onSuccess: done(true) });
  const create = useMutation({ ...createIdentityMutation(), onSuccess: done(false) });
  const busy = regenerate.isPending || create.isPending;
  return (
    <>
      <h2 className="st-h" id="st-identities">
        {t("settings.identities")}
      </h2>
      <section className="st-row">
        <div className="st-label">
          <b>{t("identities.openWith")}</b>
          <p>{t("identities.openWithNote")}</p>
        </div>
        <div className="st-choices">
          {["last", ...identities.map((who) => who.id)].map((choice) => (
            <button
              type="button"
              key={choice}
              className={`st-choice${choice === openWith ? " on" : ""}`}
              onClick={() => update({ identity: { open_with: choice } })}
            >
              {choice === "last" ? t("identities.openLast") : choice}
            </button>
          ))}
        </div>
      </section>
      <section className="st-row">
        <div className="st-label">
          <b>{t("identities.list")}</b>
          <p>{t("identities.listNote")}</p>
        </div>
        <div>
          <table className="id-table">
            <thead>
              <tr>
                <th>{t("identities.name")}</th>
                <th className="r">{t("identities.memories")}</th>
                <th className="r">{t("identities.reports")}</th>
                <th>{t("identities.folder")}</th>
                <th>{t("identities.token")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {identities.map((who) => (
                <Fragment key={who.id}>
                  <tr className={who.id === persona ? "on" : undefined}>
                    <td className="nm">
                      <span className="sh-av md">{who.id[0]?.toUpperCase()}</span>
                      {who.id}
                      {who.default && <span className="id-tag">{t("identities.default")}</span>}
                    </td>
                    <td className="r">{counts[who.id] ?? 0}</td>
                    <td className="r">{who.report_count}</td>
                    <td>{who.has_private_folder ? <span className="ok">● {t("identities.private")}</span> : "—"}</td>
                    <td>
                      {who.has_token ? (
                        <span className="ok">● {t("identities.hasToken")}</span>
                      ) : (
                        <span>○ {t("identities.noToken")}</span>
                      )}
                    </td>
                    <td className="act">
                      {who.has_token ? (
                        <button
                          type="button"
                          className="id-act"
                          disabled={busy}
                          onClick={() => {
                            if (window.confirm(t("identities.regenerateConfirm", { name: who.id })))
                              regenerate.mutate({ path: { identity: who.id } });
                          }}
                        >
                          ↻ {t("identities.regenerate")}
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="id-act"
                          disabled={busy}
                          onClick={() => create.mutate({ body: { id: who.id } })}
                        >
                          + {t("identities.issue")}
                        </button>
                      )}
                    </td>
                  </tr>
                  <tr className={`sub${who.id === persona ? " on" : ""}`}>
                    <td colSpan={6}>
                      <div className="id-agent-row">
                        <span className="lbl">{t("identities.agentConfig")}</span>
                        <AgentConfig identity={who.id} current={preferences?.identity?.agents?.[who.id] ?? ""} />
                        <Link
                          to="/settings/identities/$identity/migrate"
                          params={{ identity: who.id }}
                          className="id-migrate"
                        >
                          ↧ {t("migrate.title")}
                        </Link>
                      </div>
                    </td>
                  </tr>
                </Fragment>
              ))}
            </tbody>
          </table>
          {(regenerate.isError || create.isError) && <p className="id-error">{t("identities.failed")}</p>}
          {issued && <TokenOnce issued={issued.token} regenerated={issued.regenerated} />}
          <CreateIdentity onCreated={done(false)} />
        </div>
      </section>
    </>
  );
}

/* An identity's own Claude Code config folder: a session of that identity started from the app's line runs claude
   with it, whaat's plugin and the identity's token; curation and migration need it. */
function AgentConfig({ identity, current }: { identity: string; current: string }) {
  const { t } = useTranslation();
  const { update } = usePreferences();
  const [value, setValue] = useState(current);
  const [state, setState] = useState<"idle" | "saved" | "failed">("idle");
  useEffect(() => setValue(current), [current]);
  const save = async () => {
    if (value.trim() === current) return;
    try {
      await update({ identity: { agents: { [identity]: value.trim() } } });
      setState("saved");
      setTimeout(() => setState("idle"), 1500);
    } catch {
      setState("failed");
    }
  };
  return (
    <input
      className={`sh-search st-input id-agent${state === "failed" ? " bad" : ""}`}
      value={value}
      placeholder={t("identities.agentConfigPlaceholder")}
      title={state === "failed" ? t("identities.agentConfigFailed") : state === "saved" ? t("settings.saved") : value}
      spellCheck={false}
      onChange={(event) => {
        setValue(event.target.value);
        setState("idle");
      }}
      onBlur={save}
      onKeyDown={(event) => {
        if (event.key === "Enter") event.currentTarget.blur();
      }}
    />
  );
}
