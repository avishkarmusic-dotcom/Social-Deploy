import {
  Facebook, Globe, Instagram, Linkedin, Mail, MessageCircle, Send, Slack,
  Twitter, Youtube, type LucideIcon,
} from "lucide-react";
import type { ChannelKind } from "./types";

/** Provider marks, used only as identification — never as decoration. */
export const CHANNELS: Record<string, { label: string; Icon: LucideIcon; hue: string }> = {
  gmail: { label: "Gmail", Icon: Mail, hue: "#EA4335" },
  outlook: { label: "Outlook", Icon: Mail, hue: "#3B82F6" },
  linkedin: { label: "LinkedIn", Icon: Linkedin, hue: "#0A66C2" },
  instagram: { label: "Instagram", Icon: Instagram, hue: "#E1306C" },
  facebook: { label: "Facebook", Icon: Facebook, hue: "#1877F2" },
  messenger: { label: "Messenger", Icon: MessageCircle, hue: "#0084FF" },
  whatsapp: { label: "WhatsApp", Icon: MessageCircle, hue: "#25D366" },
  telegram: { label: "Telegram", Icon: Send, hue: "#2AABEE" },
  slack: { label: "Slack", Icon: Slack, hue: "#E01E5A" },
  discord: { label: "Discord", Icon: MessageCircle, hue: "#5865F2" },
  google_business: { label: "Business", Icon: Globe, hue: "#34A853" },
  x: { label: "X", Icon: Twitter, hue: "#8B93A1" },
  threads: { label: "Threads", Icon: Twitter, hue: "#8B93A1" },
  youtube: { label: "YouTube", Icon: Youtube, hue: "#FF0033" },
};

export const channel = (kind: ChannelKind | string) =>
  CHANNELS[kind] ?? { label: kind, Icon: Mail, hue: "#8B93A1" };
