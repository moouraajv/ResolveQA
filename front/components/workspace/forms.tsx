"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { X } from "lucide-react";
import { friendlyError } from "@/lib/resolveqa/copy";
import { useRuntime } from "./runtime";

export function NewCaseForm({ onClose }: { onClose: () => void }) {
  const r = useRuntime();
  const dialog = useRef<HTMLDialogElement>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const before = document.activeElement as HTMLElement;
    const element = dialog.current;
    element?.showModal();
    return () => {
      element?.close();
      before?.focus();
    };
  }, []);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setSaving(true);
    setError("");
    try {
      await r.addCase({
        client_id: String(f.get("company")).trim(),
        repo_ref: String(f.get("repo")).trim(),
        report_text: String(f.get("report")).trim(),
      });
      onClose();
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setSaving(false);
    }
  }
  return (
    <dialog
      className="rq-dialog"
      ref={dialog}
      onCancel={onClose}
      aria-labelledby="new-case-title"
    >
      <header>
        <h2 id="new-case-title">Novo relato</h2>
        <button
          className="rq-icon-button"
          onClick={onClose}
          aria-label="Fechar formulário"
        >
          <X size={20} />
        </button>
      </header>
      <p>Conte o que aconteceu. A triagem começa com o contexto.</p>
      <form className="rq-form" onSubmit={submit}>
        <label>
          Empresa
          <input
            name="company"
            required
            maxLength={120}
            defaultValue={
              r.mode === "demo" ? "Acme Commerce" : "resolveqa"
            }
            placeholder="Identificador da empresa"
          />
        </label>
        <label>
          Projeto
          <input
            name="repo"
            required
            maxLength={240}
            defaultValue={
              r.mode === "demo"
                ? "acme/checkout"
                : "targets/resolveqa-checkout"
            }
            placeholder="Nome do projeto"
          />
        </label>
        <label>
          Relato
          <textarea
            name="report"
            required
            minLength={10}
            maxLength={4000}
            rows={5}
            placeholder="Passos, resultado esperado e resultado observado…"
          />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <p className="form-note">
          {r.mode === "demo"
            ? "Este relato é um exemplo e não altera o trabalho da sua equipe."
            : "Sua equipe poderá acompanhar este relato e as próximas etapas."}
        </p>
        <button
          className="rq-button primary"
          disabled={saving || (r.mode === "production" && !r.config.baseUrl)}
        >
          {saving ? "Enviando…" : "Criar caso"}
        </button>
      </form>
    </dialog>
  );
}

export function ConnectionStatus() {
  const r = useRuntime();
  return (
    <section className="data-panel">
      <h2>Acompanhamento da equipe</h2>
      <p className="muted">{r.connection}</p>
      <p>
        As informações são atualizadas automaticamente. Se os casos não
        aparecerem, tente atualizar ou peça ajuda à equipe responsável.
      </p>
      <button className="rq-button" onClick={r.refresh}>
        Atualizar informações
      </button>
    </section>
  );
}
