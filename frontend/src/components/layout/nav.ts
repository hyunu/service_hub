import {
  Activity,
  Boxes,
  Container,
  LayoutDashboard,
  Network,
  Rocket,
  ScrollText,
  Settings,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/services", label: "Services", icon: Boxes },
  { to: "/containers", label: "Containers", icon: Container },
  { to: "/ports", label: "Ports & Routing", icon: Network },
  { to: "/deployments", label: "Deployments", icon: Rocket },
  { to: "/resources", label: "Resources", icon: Activity },
  { to: "/events", label: "Events", icon: ScrollText },
  { to: "/settings", label: "Settings", icon: Settings },
];
