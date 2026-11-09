import type { Channel, User } from "@/lib/graphql/types";

type ChannelSidebarProps = {
  channels: Channel[];
  selectedChannelId: string | null;
  user: User | null;
  loadingChannels: boolean;
  mobileOpen: boolean;
  onSelectChannel: (channel: Channel) => void;
  onCreateChannel: () => void;
  onOpenUser: () => void;
  onCloseMobile: () => void;
};

export function ChannelSidebar({
  channels,
  selectedChannelId,
  user,
  loadingChannels,
  mobileOpen,
  onSelectChannel,
  onCreateChannel,
  onOpenUser,
  onCloseMobile,
}: ChannelSidebarProps) {
  return (
    <>
      {mobileOpen && (
        <button className="mobile-scrim" aria-label="Cerrar canales" onClick={onCloseMobile} />
      )}
      <aside className={`sidebar${mobileOpen ? " mobile-open" : ""}`} aria-label="Canales y perfil">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">P</div>
          <div>
            <p className="brand-name">Punto de encuentro</p>
            <p className="brand-caption">Chat + encuestas · INF326</p>
          </div>
        </div>

        <div className="sidebar-heading">
          <span>Canales</span>
          <div className="sidebar-actions">
            <button className="icon-button" onClick={onCreateChannel} aria-label="Crear canal" title="Crear canal">
              <span aria-hidden="true">＋</span>
            </button>
          </div>
        </div>

        <nav className="channel-list" aria-label="Lista de canales">
          {loadingChannels && channels.length === 0 ? (
            <div className="sidebar-empty">Cargando canales…</div>
          ) : channels.length === 0 ? (
            <div className="sidebar-empty">Todavía no hay canales. Crea uno para iniciar la conversación.</div>
          ) : (
            channels.map((channel) => (
              <button
                className={`channel-button${selectedChannelId === channel.id ? " active" : ""}`}
                key={channel.id}
                onClick={() => {
                  onSelectChannel(channel);
                  onCloseMobile();
                }}
                aria-current={selectedChannelId === channel.id ? "page" : undefined}
              >
                <span className="channel-hash" aria-hidden="true">#</span>
                <span className="channel-name">{channel.name}</span>
              </button>
            ))
          )}
        </nav>

        <div className="sidebar-spacer" />

        <div className="sidebar-heading">
          <span>Perfil de demostración</span>
        </div>
        <div className="profile-card">
          <div className="avatar" aria-hidden="true">{user?.displayName.trim().charAt(0).toUpperCase() || "?"}</div>
          <div className="profile-copy">
            <p className="profile-name">{user?.displayName ?? "Selecciona un usuario"}</p>
            <p className="profile-status">● Identificador de dominio</p>
            {user?.id && <p className="profile-id" title={user.id}>{user.id}</p>}
          </div>
          <button className="icon-button" onClick={onOpenUser} aria-label="Cambiar usuario" title="Cambiar usuario">
            <span aria-hidden="true">↗</span>
          </button>
        </div>
      </aside>
    </>
  );
}
