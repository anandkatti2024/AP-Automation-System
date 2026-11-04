function Topbar({ pageTitle, username, onLogout }) {
  return (
    <header className="topbar">
      <div className="breadcrumb">
        <span>Workspace</span><span>/</span><strong>{pageTitle}</strong>
      </div>
      <div className="topbar-right">
        <span className="connection-dot" />
        <span>{username}</span>
        <button className="topbar-logout" type="button" onClick={onLogout}>
          Sign out
        </button>
        <div className="avatar" aria-hidden="true">
          {(username?.[0] || "U").toUpperCase()}
        </div>
      </div>
    </header>
  );
}

export default Topbar;
