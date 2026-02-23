import { MainNav } from "@/components/main-nav";

type AppShellProps = {
  children: React.ReactNode;
};

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="app-shell">
      <header className="top-bar">
        <div>
          <p className="eyebrow">Swing Trading Report</p>
          <h1 className="title">Operations Console</h1>
        </div>
        <MainNav />
      </header>
      <main className="main-content">{children}</main>
    </div>
  );
}
