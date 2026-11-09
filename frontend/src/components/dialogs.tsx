import { useState, type FormEvent, type ReactNode } from "react";
import type { Channel, SearchMessage, SearchMessagesInput, SearchMessagesResult } from "@/lib/graphql/types";
import { formatDateTime } from "@/lib/polls";

export function Modal({
  title,
  description,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <div className="overlay" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className={`dialog${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="dialog-header">
          <div>
            <h2 className="dialog-title">{title}</h2>
            {description && <p className="dialog-description">{description}</p>}
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Cerrar">×</button>
        </div>
        {children}
      </section>
    </div>
  );
}

export function UserDialog({
  onClose,
  onCreate,
  onLookup,
  busy,
}: {
  onClose: () => void;
  onCreate: (displayName: string) => Promise<void>;
  onLookup: (id: string) => Promise<void>;
  busy: boolean;
}) {
  const [mode, setMode] = useState<"create" | "lookup">("create");
  const [displayName, setDisplayName] = useState("");
  const [userId, setUserId] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      if (mode === "create") {
        if (!displayName.trim()) return setError("Escribe un nombre para crear el perfil.");
        await onCreate(displayName.trim());
      } else {
        if (!userId.trim()) return setError("Ingresa un ID de usuario existente.");
        await onLookup(userId.trim());
      }
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible seleccionar el usuario.");
    }
  }

  return (
    <Modal
      title="Perfil de demostración"
      description="El Gateway no autentica usuarios. Este perfil solo proporciona el ID de dominio a las operaciones."
      onClose={onClose}
    >
      <div className="form-row" role="tablist" aria-label="Modo de selección">
        <button className={mode === "create" ? "primary-button" : "secondary-button"} type="button" onClick={() => { setMode("create"); setError(null); }}>
          Crear usuario
        </button>
        <button className={mode === "lookup" ? "primary-button" : "secondary-button"} type="button" onClick={() => { setMode("lookup"); setError(null); }}>
          Usar ID existente
        </button>
      </div>
      <form className="form-stack" onSubmit={submit}>
        {mode === "create" ? (
          <label className="field-label">
            Nombre visible
            <input className="text-input" maxLength={80} value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Ej. Camila" autoFocus />
          </label>
        ) : (
          <label className="field-label">
            ID de usuario
            <input className="text-input" value={userId} onChange={(event) => setUserId(event.target.value)} placeholder="ID entregado por Users" autoFocus />
            <span className="field-help">El Gateway puede consultar un ID, pero no expone una lista de usuarios.</span>
          </label>
        )}
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="form-actions">
          <button className="secondary-button" type="button" onClick={onClose}>Cancelar</button>
          <button className="primary-button" type="submit" disabled={busy}>{busy ? "Guardando…" : mode === "create" ? "Crear y seleccionar" : "Consultar y seleccionar"}</button>
        </div>
      </form>
    </Modal>
  );
}

export function ChannelDialog({
  onClose,
  onCreate,
  busy,
}: {
  onClose: () => void;
  onCreate: (name: string) => Promise<void>;
  busy: boolean;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) return setError("El canal necesita un nombre.");
    setError(null);
    try {
      await onCreate(name.trim());
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible crear el canal.");
    }
  }

  return (
    <Modal title="Crear un canal" description="Abre un nuevo espacio para conversar con tu equipo." onClose={onClose}>
      <form className="form-stack" onSubmit={submit}>
        <label className="field-label">
          Nombre del canal
          <input className="text-input" maxLength={80} value={name} onChange={(event) => setName(event.target.value)} placeholder="Ej. ideas-de-producto" autoFocus />
        </label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="form-actions">
          <button className="secondary-button" type="button" onClick={onClose}>Cancelar</button>
          <button className="primary-button" type="submit" disabled={busy}>{busy ? "Creando…" : "Crear canal"}</button>
        </div>
      </form>
    </Modal>
  );
}

export type CreatePollForm = { question: string; options: string[]; durationMinutes: number };

export function PollDialog({
  channel,
  onClose,
  onCreate,
  busy,
}: {
  channel: Channel;
  onClose: () => void;
  onCreate: (input: CreatePollForm) => Promise<void>;
  busy: boolean;
}) {
  const [question, setQuestion] = useState("");
  const [options, setOptions] = useState(["", ""]);
  const [durationMinutes, setDurationMinutes] = useState(5);
  const [error, setError] = useState<string | null>(null);

  function updateOption(index: number, value: string) {
    setOptions((current) => current.map((option, optionIndex) => optionIndex === index ? value : option));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanedOptions = options.map((option) => option.trim());
    const normalizedOptions = cleanedOptions.map((option) => option.toLocaleLowerCase());
    if (!question.trim()) return setError("Escribe una pregunta.");
    if (cleanedOptions.length < 2 || cleanedOptions.some((option) => !option)) return setError("Completa al menos dos alternativas.");
    if (cleanedOptions.length > 10) return setError("Polls permite hasta 10 alternativas.");
    if (new Set(normalizedOptions).size !== normalizedOptions.length) return setError("Las alternativas no pueden repetirse.");
    if (!Number.isInteger(durationMinutes) || durationMinutes < 1 || durationMinutes > 1440) return setError("La duración debe estar entre 1 y 1440 minutos.");
    setError(null);
    try {
      await onCreate({ question: question.trim(), options: cleanedOptions, durationMinutes });
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible crear la encuesta.");
    }
  }

  return (
    <Modal title="Crear encuesta" description={`Se publicará en #${channel.name}. Necesitas entre 2 y 10 alternativas.`} onClose={onClose}>
      <form className="form-stack" onSubmit={submit}>
        <label className="field-label">
          Pregunta
          <input className="text-input" maxLength={500} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="¿Qué tema revisamos primero?" autoFocus />
        </label>
        <div className="field-label">
          Alternativas
          {options.map((option, index) => (
            <div className="option-editor" key={index}>
              <input className="text-input" maxLength={200} value={option} onChange={(event) => updateOption(index, event.target.value)} placeholder={`Alternativa ${index + 1}`} aria-label={`Alternativa ${index + 1}`} />
              {options.length > 2 && (
                <button className="icon-button" type="button" aria-label={`Quitar alternativa ${index + 1}`} onClick={() => setOptions((current) => current.filter((_, optionIndex) => optionIndex !== index))}>×</button>
              )}
            </div>
          ))}
          {options.length < 10 && <button className="text-button" type="button" onClick={() => setOptions((current) => [...current, ""])}>＋ Agregar alternativa</button>}
        </div>
        <label className="field-label">
          Duración en minutos
          <input className="text-input" type="number" min={1} max={1440} value={durationMinutes} onChange={(event) => setDurationMinutes(Number(event.target.value))} />
        </label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="form-actions">
          <button className="secondary-button" type="button" onClick={onClose}>Cancelar</button>
          <button className="primary-button" type="submit" disabled={busy}>{busy ? "Publicando…" : "Crear encuesta"}</button>
        </div>
      </form>
    </Modal>
  );
}

export function SearchDialog({
  channels,
  initialChannelId,
  onClose,
  onSearch,
  onNavigate,
}: {
  channels: Channel[];
  initialChannelId: string | null;
  onClose: () => void;
  onSearch: (input: SearchMessagesInput) => Promise<SearchMessagesResult>;
  onNavigate: (result: SearchMessage) => void;
}) {
  const [content, setContent] = useState("");
  const [authorId, setAuthorId] = useState("");
  const [mentionId, setMentionId] = useState("");
  const [channelId, setChannelId] = useState(initialChannelId ?? "");
  const [minDate, setMinDate] = useState("");
  const [maxDate, setMaxDate] = useState("");
  const [hasLink, setHasLink] = useState(false);
  const [hasMention, setHasMention] = useState(false);
  const [sortBy, setSortBy] = useState<"TIMESTAMP" | "RELEVANCE">("RELEVANCE");
  const [sortOrder, setSortOrder] = useState<"ASC" | "DESC">("DESC");
  const [result, setResult] = useState<SearchMessagesResult | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const limit = 10;

  async function search(nextOffset: number) {
    const has = [ ...(hasLink ? ["LINK" as const] : []), ...(hasMention ? ["MENTION" as const] : []) ];
    const input: SearchMessagesInput = {
      content: content.trim() || undefined,
      authorIds: authorId.trim() ? [authorId.trim()] : undefined,
      channelIds: channelId ? [channelId] : undefined,
      mentions: mentionId.trim() ? [mentionId.trim()] : undefined,
      has: has.length ? has : undefined,
      minDate: minDate ? `${minDate}T00:00:00.000Z` : undefined,
      maxDate: maxDate ? `${maxDate}T23:59:59.999Z` : undefined,
      sortBy,
      sortOrder,
      limit,
      offset: nextOffset,
    };
    if (!input.content && !input.authorIds && !input.channelIds && !input.mentions && !input.has && !input.minDate && !input.maxDate) {
      setError("Ingresa texto o al menos un filtro para buscar.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const found = await onSearch(input);
      setResult(found);
      setOffset(nextOffset);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible completar la búsqueda.");
    } finally {
      setLoading(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void search(0);
  }

  return (
    <Modal title="Búsqueda avanzada" description="Busca mensajes por contenido, canal, autor, fechas o atributos." onClose={onClose} wide>
      <form className="form-stack" onSubmit={submit}>
        <label className="field-label">
          Contenido
          <input className="text-input" value={content} onChange={(event) => setContent(event.target.value)} placeholder="Palabras o frase" />
        </label>
        <div className="form-row">
          <label className="field-label" style={{ flex: 1 }}>
            Canal
            <select className="select-input" value={channelId} onChange={(event) => setChannelId(event.target.value)}>
              <option value="">Todos los canales</option>
              {channels.map((channel) => <option value={channel.id} key={channel.id}># {channel.name}</option>)}
            </select>
          </label>
          <label className="field-label" style={{ flex: 1 }}>
            ID del autor
            <input className="text-input" value={authorId} onChange={(event) => setAuthorId(event.target.value)} placeholder="ID de Users" />
          </label>
        </div>
        <label className="field-label">
          ID mencionado
          <input className="text-input" value={mentionId} onChange={(event) => setMentionId(event.target.value)} placeholder="ID de usuario mencionado" />
        </label>
        <div className="form-row">
          <label className="field-label" style={{ flex: 1 }}>
            Desde
            <input className="text-input" type="date" value={minDate} onChange={(event) => setMinDate(event.target.value)} />
          </label>
          <label className="field-label" style={{ flex: 1 }}>
            Hasta
            <input className="text-input" type="date" value={maxDate} onChange={(event) => setMaxDate(event.target.value)} />
          </label>
        </div>
        <div className="form-row">
          <label className="field-label" style={{ flex: 1 }}>
            Ordenar por
            <select className="select-input" value={sortBy} onChange={(event) => setSortBy(event.target.value as "TIMESTAMP" | "RELEVANCE")}>
              <option value="RELEVANCE">Relevancia</option>
              <option value="TIMESTAMP">Fecha</option>
            </select>
          </label>
          <label className="field-label" style={{ flex: 1 }}>
            Dirección
            <select className="select-input" value={sortOrder} onChange={(event) => setSortOrder(event.target.value as "ASC" | "DESC")}>
              <option value="DESC">Descendente</option>
              <option value="ASC">Ascendente</option>
            </select>
          </label>
        </div>
        <div className="form-row">
          <label className="muted"><input type="checkbox" checked={hasLink} onChange={(event) => setHasLink(event.target.checked)} /> Contiene enlaces</label>
          <label className="muted"><input type="checkbox" checked={hasMention} onChange={(event) => setHasMention(event.target.checked)} /> Contiene menciones</label>
          <button className="primary-button" type="submit" disabled={loading}>{loading ? "Buscando…" : "Buscar mensajes"}</button>
        </div>
        {error && <p className="form-error" role="alert">{error}</p>}
      </form>

      {result && (
        <>
          <p className="dialog-description" aria-live="polite">
            {result.totalResults} {result.totalResults === 1 ? "resultado" : "resultados"}
            {result.messages.length > 0 && ` · mostrando ${offset + 1}–${offset + result.messages.length}`}
          </p>
          <div className="dialog-results">
            {result.messages.length === 0 ? <p className="muted">No se encontraron mensajes con esos filtros.</p> : result.messages.map((message) => (
              <button className="search-result" type="button" key={message.id} onClick={() => onNavigate(message)}>
                <span className="search-result-top"><span>#{channels.find((channel) => channel.id === message.channelId)?.name ?? message.channelId} · {message.authorId}</span><time dateTime={message.createdAt}>{formatDateTime(message.createdAt)}</time></span>
                <span className="search-result-content">{message.content}</span>
              </button>
            ))}
          </div>
          <div className="form-actions">
            <button className="secondary-button" type="button" disabled={loading || offset === 0} onClick={() => void search(Math.max(0, offset - limit))}>Anterior</button>
            <button className="secondary-button" type="button" disabled={loading || offset + limit >= Math.min(result.totalResults, 9976)} onClick={() => void search(offset + limit)}>Siguiente</button>
          </div>
        </>
      )}
    </Modal>
  );
}
