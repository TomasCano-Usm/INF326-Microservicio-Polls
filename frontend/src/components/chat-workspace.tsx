"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ChannelSidebar } from "@/components/channel-sidebar";
import { ChannelDialog, PollDialog, SearchDialog, UserDialog, type CreatePollForm } from "@/components/dialogs";
import { MessageComposer } from "@/components/message-composer";
import { MessageFeed } from "@/components/message-feed";
import {
  ADD_REACTION_MUTATION,
  CHANNELS_QUERY,
  CHANNEL_QUERY,
  CHANNEL_WORKSPACE_QUERY,
  CLOSE_POLL_MUTATION,
  CREATE_CHANNEL_MUTATION,
  CREATE_POLL_MUTATION,
  CREATE_USER_MUTATION,
  POLL_QUERY,
  REMOVE_REACTION_MUTATION,
  SEARCH_MESSAGES_QUERY,
  SEND_MESSAGE_MUTATION,
  USER_QUERY,
  VOTE_MUTATION,
} from "@/lib/graphql/operations";
import { errorStatus, graphqlRequest, GraphqlTransportError } from "@/lib/graphql/client";
import type {
  Channel,
  GraphqlError,
  Message,
  Poll,
  SearchMessagesInput,
  SearchMessagesResult,
  User,
  Vote,
} from "@/lib/graphql/types";
import { mergePolls } from "@/lib/polls";

type DialogKind = "user" | "channel" | "poll" | "search" | null;
type Notice = { message: string; kind: "info" | "error" };
type WorkspacePayload = { messages: Message[]; polls: Poll[] };
type PollPayload = { poll: Poll | null };
type VotePayload = { vote: Vote };
type StoredProfile = { id: string; displayName: string };

const PROFILE_STORAGE_KEY = "inf326-demo-profile";
const CHANNEL_STORAGE_KEY = "inf326-selected-channel";

const SERVICE_LABELS: Record<string, string> = {
  polls: "Encuestas",
  users: "Usuarios",
  channels: "Canales",
  messages: "Mensajes",
  reactions: "Reacciones",
  search: "Búsqueda",
};

class OperationError extends Error {
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "OperationError";
    this.status = status;
  }
}

function graphqlIssue(errors: GraphqlError[] | undefined, fallback: string): OperationError {
  const status = errorStatus(errors);
  if (status === 422) return new OperationError("Revisa los datos ingresados e inténtalo nuevamente.", status);
  if (status === 403) return new OperationError("Esta operación no está permitida para el usuario indicado.", status);
  if (status === 404) return new OperationError("No se encontró el recurso solicitado.", status);
  if (status === 409) return new OperationError("La operación entra en conflicto con el estado actual.", status);
  const service = errors?.find((error) => typeof error.extensions?.service === "string")?.extensions?.service;
  const label = typeof service === "string" ? SERVICE_LABELS[service] : undefined;
  return new OperationError(label ? `${label} no está disponible por ahora. Intenta de nuevo.` : fallback, status);
}

function requireValue<T>(value: T | null | undefined, errors: GraphqlError[] | undefined, fallback: string): T {
  if (errors?.length) throw graphqlIssue(errors, fallback);
  if (value === null || value === undefined) throw new OperationError(fallback);
  return value;
}

function getTransportMessage(error: unknown): string {
  if (error instanceof OperationError) return error.message;
  if (error instanceof Error && error.name === "AbortError") return "La solicitud se canceló porque cambió el canal.";
  if (error instanceof GraphqlTransportError && error.status === 504) {
    return "El Gateway tardó demasiado en responder. Intenta nuevamente.";
  }
  return "No fue posible comunicarse con el Gateway GraphQL. Comprueba el port-forward y vuelve a intentar.";
}

function activePollConflictMessage(poll: Poll | null): string {
  if (poll?.status === "closed") return "La encuesta ya está cerrada y no acepta votos.";
  if (poll?.status === "pending_announcement") return "La encuesta todavía está pendiente de publicación y no acepta votos.";
  if (poll?.status === "creation_failed") return "La encuesta no pudo publicarse.";
  return "El Gateway rechazó el voto. Puede que este perfil ya haya votado.";
}

function idempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `poll-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function profileFromStorage(value: string | null): User | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value) as Partial<StoredProfile>;
    if (typeof parsed.id === "string" && typeof parsed.displayName === "string") {
      return { id: parsed.id, displayName: parsed.displayName };
    }
  } catch {
    return null;
  }
  return null;
}

export function ChatWorkspace() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [selectedChannelId, setSelectedChannelId] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [remotePolls, setRemotePolls] = useState<Poll[]>([]);
  const [createdPolls, setCreatedPolls] = useState<Poll[]>([]);
  const [loadedChannelId, setLoadedChannelId] = useState<string | null>(null);
  const [channelsLoading, setChannelsLoading] = useState(true);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<DialogKind>(null);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [busyPollId, setBusyPollId] = useState<string | null>(null);
  const [votedByProfile, setVotedByProfile] = useState<Record<string, string[]>>({});
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [highlightedMessageId, setHighlightedMessageId] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [searchInitialChannelId, setSearchInitialChannelId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const channelTitle = channels.find((channel) => channel.id === selectedChannelId)?.name;
  const channelLoaded = loadedChannelId === selectedChannelId;
  const visibleMessages = channelLoaded ? messages : [];
  const displayPolls = useMemo(() => {
    const local = createdPolls.filter((poll) => poll.channelId === selectedChannelId);
    const remote = channelLoaded ? remotePolls : [];
    return mergePolls(local, remote);
  }, [channelLoaded, createdPolls, remotePolls, selectedChannelId]);
  const votedPollIds = useMemo(
    () => new Set(user ? votedByProfile[user.id] ?? [] : []),
    [user, votedByProfile],
  );

  const showNotice = useCallback((message: string, kind: Notice["kind"] = "info") => {
    setNotice({ message, kind });
  }, []);

  const refreshWorkspace = useCallback(() => setRefreshVersion((version) => version + 1), []);

  const loadChannels = useCallback(async () => {
    setChannelsLoading(true);
    try {
      const response = await graphqlRequest<{ channels: Channel[] }>(CHANNELS_QUERY);
      const nextChannels = requireValue(response.data?.channels, response.errors, "No fue posible cargar los canales.");
      setChannels(nextChannels);
      setSelectedChannelId((current) => {
        const stored = typeof window === "undefined" ? null : window.localStorage.getItem(CHANNEL_STORAGE_KEY);
        const preferred = current ?? stored;
        if (preferred && nextChannels.some((channel) => channel.id === preferred)) return preferred;
        return nextChannels[0]?.id ?? null;
      });
    } catch (error) {
      showNotice(getTransportMessage(error), "error");
    } finally {
      setChannelsLoading(false);
    }
  }, [showNotice]);

  useEffect(() => {
    const storedUser = profileFromStorage(window.localStorage.getItem(PROFILE_STORAGE_KEY));
    setUser(storedUser);
    setSelectedChannelId(window.localStorage.getItem(CHANNEL_STORAGE_KEY));
    if (!storedUser) setDialog("user");
    void loadChannels();
  }, [loadChannels]);

  useEffect(() => {
    const userId = user?.id;
    if (!userId) return;
    let cancelled = false;
    void graphqlRequest<{ user: User | null }, { id: string }>(USER_QUERY, { id: userId })
      .then((response) => {
        if (cancelled) return;
        const verified = response.data?.user;
        if (verified) {
          setUser(verified);
          window.localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(verified));
        } else if (!response.errors?.length) {
          setUser((current) => current?.id === userId ? { ...current, displayName: `Usuario ${userId}` } : current);
        }
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [user?.id]);

  useEffect(() => {
    if (!selectedChannelId) return;
    let cancelled = false;
    void graphqlRequest<{ channel: Channel | null }, { id: string }>(CHANNEL_QUERY, { id: selectedChannelId })
      .then((response) => {
        if (cancelled || !response.data?.channel) return;
        const selected = response.data.channel;
        setChannels((current) => current.map((channel) => channel.id === selected.id ? selected : channel));
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [selectedChannelId]);

  useEffect(() => {
    if (!selectedChannelId) return;
    window.localStorage.setItem(CHANNEL_STORAGE_KEY, selectedChannelId);
  }, [selectedChannelId]);

  useEffect(() => {
    if (!selectedChannelId) {
      setWorkspaceLoading(false);
      return;
    }

    let disposed = false;
    let inFlight = false;
    let controller: AbortController | null = null;
    const loadWorkspace = async (silent: boolean) => {
      if (disposed || document.visibilityState === "hidden" || inFlight) return;
      inFlight = true;
      controller = new AbortController();
      if (!silent) setWorkspaceLoading(true);
      try {
        const response = await graphqlRequest<WorkspacePayload, { channelId: string }>(
          CHANNEL_WORKSPACE_QUERY,
          { channelId: selectedChannelId },
          controller.signal,
        );
        if (disposed || controller.signal.aborted) return;
        if (response.data) {
          setMessages(response.data.messages ?? []);
          setRemotePolls(response.data.polls ?? []);
          setLoadedChannelId(selectedChannelId);
          setWorkspaceError(response.errors?.length ? graphqlIssue(response.errors, "Algunos datos del canal no están disponibles.").message : null);
        } else {
          setWorkspaceError(graphqlIssue(response.errors, "No fue posible cargar la conversación.").message);
        }
      } catch (error) {
        if (!disposed && !(error instanceof Error && error.name === "AbortError")) {
          setWorkspaceError(getTransportMessage(error));
        }
      } finally {
        inFlight = false;
        controller = null;
        if (!disposed && !silent) setWorkspaceLoading(false);
      }
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void loadWorkspace(true);
    };

    void loadWorkspace(false);
    const interval = window.setInterval(() => void loadWorkspace(true), 15_000);
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      disposed = true;
      controller?.abort();
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [refreshVersion, selectedChannelId]);

  const pendingPollIds = useMemo(
    () => createdPolls
      .filter((poll) => poll.channelId === selectedChannelId && poll.status === "pending_announcement")
      .map((poll) => poll.pollId),
    [createdPolls, selectedChannelId],
  );

  useEffect(() => {
    if (pendingPollIds.length === 0) return;
    let disposed = false;
    let inFlight = false;
    const controllers = new Set<AbortController>();

    const refreshPendingPolls = async () => {
      if (disposed || document.visibilityState === "hidden" || inFlight) return;
      inFlight = true;
      await Promise.all(pendingPollIds.map(async (pollId) => {
        const controller = new AbortController();
        controllers.add(controller);
        try {
          const response = await graphqlRequest<PollPayload, { id: string }>(POLL_QUERY, { id: pollId }, controller.signal);
          const poll = response.data?.poll;
          if (disposed || !poll) return;
          setCreatedPolls((current) => mergePolls(current, [poll]));
        } catch {
          // A transient lookup failure is retried on the next interval.
        } finally {
          controllers.delete(controller);
        }
      }));
      inFlight = false;
    };

    void refreshPendingPolls();
    const interval = window.setInterval(() => void refreshPendingPolls(), 5_000);
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void refreshPendingPolls();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      disposed = true;
      controllers.forEach((controller) => controller.abort());
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [pendingPollIds]);

  useEffect(() => {
    if (!notice) return;
    const timeout = window.setTimeout(() => setNotice(null), notice.kind === "error" ? 7000 : 4200);
    return () => window.clearTimeout(timeout);
  }, [notice]);

  async function createUser(displayName: string) {
    setBusyAction("user");
    try {
      const response = await graphqlRequest<{ createUser: User }, { displayName: string }>(CREATE_USER_MUTATION, { displayName });
      const created = requireValue(response.data?.createUser, response.errors, "No fue posible crear el usuario.");
      setUser(created);
      window.localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(created));
      showNotice(`Perfil de demostración listo: ${created.displayName}. No es una sesión autenticada.`);
    } finally {
      setBusyAction(null);
    }
  }

  async function selectExistingUser(id: string) {
    setBusyAction("user");
    try {
      const response = await graphqlRequest<{ user: User | null }, { id: string }>(USER_QUERY, { id });
      const found = requireValue(response.data?.user, response.errors, "No se encontró ese usuario.");
      setUser(found);
      window.localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(found));
      showNotice(`Perfil seleccionado: ${found.displayName}. Esto no autentica al usuario.`);
    } finally {
      setBusyAction(null);
    }
  }

  async function createChannel(name: string) {
    setBusyAction("channel");
    try {
      const response = await graphqlRequest<{ createChannel: Channel }, { name: string }>(CREATE_CHANNEL_MUTATION, { name });
      const created = requireValue(response.data?.createChannel, response.errors, "No fue posible crear el canal.");
      setChannels((current) => [...current.filter((channel) => channel.id !== created.id), created]);
      setSelectedChannelId(created.id);
      showNotice(`Canal #${created.name} creado.`);
    } finally {
      setBusyAction(null);
    }
  }

  async function sendMessage(content: string) {
    if (!selectedChannelId || !user) {
      setDialog("user");
      return showNotice("Selecciona un usuario de demostración antes de enviar mensajes.", "error");
    }
    setSending(true);
    try {
      const response = await graphqlRequest<{ sendMessage: Message }, { channelId: string; authorId: string; content: string }>(
        SEND_MESSAGE_MUTATION,
        { channelId: selectedChannelId, authorId: user.id, content },
      );
      const sent = requireValue(response.data?.sendMessage, response.errors, "No fue posible enviar el mensaje.");
      setMessages((current) => current.some((message) => message.id === sent.id) ? current : [...current, { ...sent, author: user, reactions: null }]);
      setLoadedChannelId(selectedChannelId);
      setWorkspaceError(null);
      refreshWorkspace();
    } catch (error) {
      showNotice(getTransportMessage(error), "error");
      throw error;
    } finally {
      setSending(false);
    }
  }

  async function createPoll(input: CreatePollForm) {
    if (!selectedChannelId || !user) throw new OperationError("Selecciona un usuario y un canal antes de crear una encuesta.");
    setBusyAction("poll");
    try {
      const response = await graphqlRequest<{ createPoll: Poll }, { input: Record<string, unknown>; idempotencyKey: string }>(
        CREATE_POLL_MUTATION,
        {
          input: {
            channelId: selectedChannelId,
            authorId: user.id,
            question: input.question,
            options: input.options,
            durationMinutes: input.durationMinutes,
          },
          idempotencyKey: idempotencyKey(),
        },
      );
      const created = requireValue(response.data?.createPoll, response.errors, "No fue posible crear la encuesta.");
      setCreatedPolls((current) => mergePolls(current, [created]));
      showNotice(created.status === "pending_announcement" ? "Encuesta creada. Esperando que Messages publique el anuncio." : "Encuesta creada y lista para votar.");
      refreshWorkspace();
    } finally {
      setBusyAction(null);
    }
  }

  async function refreshSinglePoll(pollId: string): Promise<Poll | null> {
    try {
      const response = await graphqlRequest<PollPayload, { id: string }>(POLL_QUERY, { id: pollId });
      return response.data?.poll ?? null;
    } catch {
      return null;
    }
  }

  async function vote(poll: Poll, optionId: string) {
    if (!user) {
      setDialog("user");
      return showNotice("Selecciona un usuario de demostración antes de votar.", "error");
    }
    if (poll.status !== "open") return;
    if (votedPollIds.has(poll.pollId)) return;
    setBusyPollId(poll.pollId);
    try {
      const response = await graphqlRequest<VotePayload, { pollId: string; voterId: string; optionId: string }>(
        VOTE_MUTATION,
        { pollId: poll.pollId, voterId: user.id, optionId },
      );
      if (response.errors?.length || !response.data?.vote) {
        const status = errorStatus(response.errors);
        if (status === 409) {
          const latest = await refreshSinglePoll(poll.pollId);
          if (latest) setCreatedPolls((current) => mergePolls(current, [latest]));
          if (latest?.status === "open") {
            setVotedByProfile((current) => ({ ...current, [user.id]: [...new Set([...(current[user.id] ?? []), poll.pollId])] }));
          }
          showNotice(activePollConflictMessage(latest), "error");
          refreshWorkspace();
          return;
        }
        if (status === 422) {
          showNotice("La alternativa seleccionada no es válida para esta encuesta. Actualiza la conversación.", "error");
          refreshWorkspace();
          return;
        }
        throw graphqlIssue(response.errors, "No fue posible registrar el voto.");
      }

      setVotedByProfile((current) => ({ ...current, [user.id]: [...new Set([...(current[user.id] ?? []), poll.pollId])] }));
      showNotice("Tu voto fue registrado. Actualizando resultados…");
      const latest = await refreshSinglePoll(poll.pollId);
      if (latest) setCreatedPolls((current) => mergePolls(current, [latest]));
      refreshWorkspace();
    } catch (error) {
      showNotice(getTransportMessage(error), "error");
    } finally {
      setBusyPollId(null);
    }
  }

  async function closePoll(poll: Poll) {
    if (!user || user.id !== poll.authorId || poll.status !== "open") return;
    setBusyPollId(poll.pollId);
    try {
      const response = await graphqlRequest<{ closePoll: Poll }, { pollId: string; authorId: string }>(
        CLOSE_POLL_MUTATION,
        { pollId: poll.pollId, authorId: user.id },
      );
      const closed = requireValue(response.data?.closePoll, response.errors, "No fue posible cerrar la encuesta.");
      setCreatedPolls((current) => mergePolls(current, [closed]));
      showNotice("Encuesta cerrada. Los resultados ya están disponibles.");
      refreshWorkspace();
    } catch (error) {
      showNotice(getTransportMessage(error), "error");
    } finally {
      setBusyPollId(null);
    }
  }

  async function addReaction(message: Message, reactionType: string) {
    if (!user) return setDialog("user");
    setBusyAction(`reaction-${message.id}`);
    try {
      const response = await graphqlRequest<{ addReaction: unknown }, { messageId: string; channelId: string; userId: string; reactionType: string }>(
        ADD_REACTION_MUTATION,
        { messageId: message.id, channelId: message.channelId, userId: user.id, reactionType },
      );
      requireValue(response.data?.addReaction, response.errors, "No fue posible agregar la reacción.");
      refreshWorkspace();
    } catch (error) {
      if (error instanceof OperationError && error.status === 409) {
        showNotice("Esta reacción podría estar ya agregada para este perfil. Actualizando el mensaje…", "error");
        refreshWorkspace();
      } else {
        showNotice(getTransportMessage(error), "error");
      }
    } finally {
      setBusyAction(null);
    }
  }

  async function removeReaction(message: Message, reactionId: string) {
    setBusyAction(`reaction-${message.id}`);
    try {
      const response = await graphqlRequest<{ removeReaction: boolean }, { reactionId: string }>(REMOVE_REACTION_MUTATION, { reactionId });
      requireValue(response.data?.removeReaction, response.errors, "No fue posible quitar la reacción.");
      refreshWorkspace();
    } catch (error) {
      showNotice(getTransportMessage(error), "error");
    } finally {
      setBusyAction(null);
    }
  }

  async function searchMessages(input: SearchMessagesInput): Promise<SearchMessagesResult> {
    const response = await graphqlRequest<{ searchMessages: SearchMessagesResult }, { input: SearchMessagesInput }>(
      SEARCH_MESSAGES_QUERY,
      { input },
    );
    return requireValue(response.data?.searchMessages, response.errors, "No fue posible completar la búsqueda.");
  }

  function navigateToSearchResult(result: { id: string; channelId: string }) {
    const channel = channels.find((item) => item.id === result.channelId);
    if (!channel) {
      setDialog(null);
      return showNotice("El canal del resultado no aparece en la lista actual.", "error");
    }
    setDialog(null);
    setSelectedChannelId(channel.id);
    setHighlightedMessageId(result.id);
    setRefreshVersion((version) => version + 1);
  }

  function chooseChannel(channel: Channel) {
    setWorkspaceError(null);
    setSelectedChannelId(channel.id);
    setHighlightedMessageId(null);
  }

  const requireProfile = !user;

  return (
    <main className="app-shell">
      <ChannelSidebar
        channels={channels}
        selectedChannelId={selectedChannelId}
        user={user}
        loadingChannels={channelsLoading}
        mobileOpen={mobileSidebarOpen}
        onSelectChannel={chooseChannel}
        onCreateChannel={() => setDialog("channel")}
        onOpenUser={() => setDialog("user")}
        onCloseMobile={() => setMobileSidebarOpen(false)}
      />

      <section className="workspace">
        <header className="chat-header">
          <button className="icon-button mobile-menu" type="button" aria-label="Abrir canales" onClick={() => setMobileSidebarOpen(true)}>☰</button>
          <div className="channel-title-wrap">
            <p className="channel-kicker">Espacio compartido</p>
            <h1 className="channel-title">{channelTitle ? `# ${channelTitle}` : "Conversaciones"}</h1>
            <p className="header-subtitle">Mensajes, ideas y decisiones del equipo</p>
          </div>
          <div className="header-actions">
            {!user && <button className="header-button" type="button" onClick={() => setDialog("user")}>Seleccionar perfil</button>}
            <button className="header-button" type="button" onClick={() => { setSearchInitialChannelId(selectedChannelId); setDialog("search"); }}>
              <span className="button-symbol" aria-hidden="true">⌕</span><span className="button-word">Buscar</span>
            </button>
            <button className="header-button accent" type="button" disabled={!selectedChannelId || requireProfile} onClick={() => setDialog("poll")} title={requireProfile ? "Selecciona un perfil primero" : "Crear encuesta"}>
              <span className="button-symbol" aria-hidden="true">◈</span><span className="button-word">Encuesta</span>
            </button>
          </div>
        </header>

        {!selectedChannelId ? (
          <div className="conversation">
            <div className="empty-state">
              <div className="empty-icon" aria-hidden="true">#</div>
              <h2 className="empty-title">Elige tu primer canal</h2>
              <p className="empty-copy">Selecciona un canal en la barra lateral o crea uno para comenzar.</p>
              <div style={{ marginTop: 16 }}><button className="primary-button" type="button" onClick={() => setDialog("channel")}>＋ Crear canal</button></div>
            </div>
          </div>
        ) : (
          <div className="conversation">
            <MessageFeed
              messages={visibleMessages}
              polls={displayPolls}
              user={user}
              loading={workspaceLoading}
              error={workspaceError}
              busyPollId={busyPollId}
              busyReactionMessageId={busyAction?.startsWith("reaction-") ? busyAction.slice("reaction-".length) : null}
              votedPollIds={votedPollIds}
              highlightedMessageId={highlightedMessageId}
              onRetry={refreshWorkspace}
              onVote={vote}
              onClosePoll={closePoll}
              onAddReaction={addReaction}
              onRemoveReaction={removeReaction}
            />
            <MessageComposer
              disabled={!user}
              sending={sending}
              channelName={channelTitle}
              onSend={sendMessage}
            />
          </div>
        )}
      </section>

      {notice && (
        <div className={`notice${notice.kind === "error" ? " error" : ""}`} role={notice.kind === "error" ? "alert" : "status"}>
          {notice.message}
          <div className="notice-actions"><button className="text-button" type="button" onClick={() => setNotice(null)}>Cerrar</button></div>
        </div>
      )}

      {dialog === "user" && <UserDialog onClose={() => setDialog(null)} onCreate={createUser} onLookup={selectExistingUser} busy={busyAction === "user"} />}
      {dialog === "channel" && <ChannelDialog onClose={() => setDialog(null)} onCreate={createChannel} busy={busyAction === "channel"} />}
      {dialog === "poll" && selectedChannelId && channelTitle && <PollDialog channel={{ id: selectedChannelId, name: channelTitle }} onClose={() => setDialog(null)} onCreate={createPoll} busy={busyAction === "poll"} />}
      {dialog === "search" && <SearchDialog channels={channels} initialChannelId={searchInitialChannelId} onClose={() => setDialog(null)} onSearch={searchMessages} onNavigate={navigateToSearchResult} />}
    </main>
  );
}
