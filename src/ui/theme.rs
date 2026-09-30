use ratatui::style::{Color, Modifier, Style};

#[derive(Clone, Copy)]
pub(super) struct Theme {
    pub accent: Color,
    pub accent_alt: Color,
    pub text: Color,
    pub subtle: Color,
    pub border: Color,
    pub error: Color,
    pub success: Color,
    pub warning: Color,
    pub background: Color,
}

impl Theme {
    pub fn by_name(name: &str) -> Self {
        let colors = match name {
            "oc-1" => [
                0xfab283, 0x034cff, 0xf5f5f5, 0xb8b0b0, 0x3a3333, 0xfc533a, 0x12c905, 0xfcd53a,
                0x1c1818,
            ],
            "tokyonight" => [
                0x7aa2f7, 0x7aa2f7, 0xc0caf5, 0x7a88cf, 0x3a3e57, 0xf7768e, 0x9ece6a, 0xe0af68,
                0x1a1b26,
            ],
            "dracula" => [
                0xbd93f9, 0xbd93f9, 0xf8f8f2, 0xb6b9e4, 0x3f415a, 0xff5555, 0x50fa7b, 0xffb86c,
                0x282a36,
            ],
            "monokai" => [
                0xae81ff, 0xae81ff, 0xf8f8f2, 0xc5c5c0, 0x494a3a, 0xf92672, 0xa6e22e, 0xfd971f,
                0x272822,
            ],
            "solarized" => [
                0x6c71c4, 0x6c71c4, 0x93a1a1, 0x6c7f80, 0x31505b, 0xdc322f, 0x859900, 0xb58900,
                0x002b36,
            ],
            "catppuccin" => [
                0xb4befe, 0xb4befe, 0xcdd6f4, 0xa6adc8, 0x4a4763, 0xf38ba8, 0xa6d189, 0xf4b8e4,
                0x1e1e2e,
            ],
            "ayu" => [
                0x39bae6, 0x39bae6, 0xced0d6, 0x8f9aa5, 0x3d4555, 0xff8f77, 0x7fd962, 0xebb062,
                0x0f1419,
            ],
            "onedarkpro" => [
                0x61afef, 0x61afef, 0xabb2bf, 0x818899, 0x4a5164, 0xe06c75, 0x98c379, 0xe5c07b,
                0x1e222a,
            ],
            "shadesofpurple" => [
                0xc792ff, 0xc792ff, 0xf5f0ff, 0xc9b6ff, 0x4d3a73, 0xff7ac6, 0x7be0b0, 0xffd580,
                0x1a102b,
            ],
            "nightowl" => [
                0x82aaff, 0x82aaff, 0xd6deeb, 0x5f7e97, 0x3a5a75, 0xef5350, 0xc5e478, 0xecc48d,
                0x011627,
            ],
            "vesper" => [
                0xffc799, 0xffc799, 0xffffff, 0xa0a0a0, 0x282828, 0xff8080, 0x99ffe4, 0xffc799,
                0x101010,
            ],
            "gruvbox" => [
                0xfabd2f, 0x83a598, 0xebdbb2, 0xa89984, 0x504945, 0xfb4934, 0xb8bb26, 0xfe8019,
                0x282828,
            ],
            "charm" => [
                0xa78bfa, 0x6ee7a7, 0xeaeaea, 0x9b9b9b, 0x3a3a3a, 0xff5c72, 0xa3be8c, 0xebcb8b,
                0x202020,
            ],
            _ => [
                0x88c0d0, 0x88c0d0, 0xe5e9f0, 0xd8dee9, 0x4c566a, 0xbf616a, 0xa3be8c, 0xebcb8b,
                0x2e3440,
            ],
        };
        Self::from_colors(colors)
    }

    fn from_colors(colors: [u32; 9]) -> Self {
        let colors = colors.map(rgb);
        Self {
            accent: colors[0],
            accent_alt: colors[1],
            text: colors[2],
            subtle: colors[3],
            border: colors[4],
            error: colors[5],
            success: colors[6],
            warning: colors[7],
            background: colors[8],
        }
    }

    pub fn text(self) -> Style {
        Style::default().fg(self.text).bg(self.background)
    }
    pub fn title(self) -> Style {
        self.text().fg(self.accent).add_modifier(Modifier::BOLD)
    }
    pub fn subtle(self) -> Style {
        self.text().fg(self.subtle)
    }
    pub fn selected(self) -> Style {
        self.chip(self.accent)
    }
    pub fn chip(self, color: Color) -> Style {
        let foreground = match color {
            Color::Rgb(r, g, b)
                if (299 * u32::from(r) + 587 * u32::from(g) + 114 * u32::from(b)) > 140_000 =>
            {
                Color::Rgb(26, 26, 26)
            }
            _ => Color::Rgb(245, 245, 245),
        };
        Style::default()
            .bg(color)
            .fg(foreground)
            .add_modifier(Modifier::BOLD)
    }
    pub fn selection(self) -> Style {
        let background = match (self.accent, self.border) {
            (Color::Rgb(r1, g1, b1), Color::Rgb(r2, g2, b2)) => Color::Rgb(
                ((u16::from(r1) + u16::from(r2)) / 2) as u8,
                ((u16::from(g1) + u16::from(g2)) / 2) as u8,
                ((u16::from(b1) + u16::from(b2)) / 2) as u8,
            ),
            _ => self.border,
        };
        self.text().bg(background).add_modifier(Modifier::BOLD)
    }
    pub fn bar(self) -> Style {
        self.subtle().bg(self.border)
    }
    pub fn bar_key(self) -> Style {
        self.bar().fg(self.accent_alt).add_modifier(Modifier::BOLD)
    }
    pub fn role(self, role: &str) -> Style {
        let color = match role {
            "success" => self.success,
            "warning" => self.warning,
            "error" => self.error,
            "muted" => self.subtle,
            _ => self.text,
        };
        self.text().fg(color)
    }
}

fn rgb(value: u32) -> Color {
    Color::Rgb((value >> 16) as u8, (value >> 8) as u8, value as u8)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registered_themes_have_distinct_palettes_and_readable_selection() {
        let palettes: Vec<_> = crate::config::THEMES
            .iter()
            .map(|name| Theme::by_name(name))
            .collect();
        assert_eq!(palettes.len(), 14);
        assert!(
            palettes
                .iter()
                .all(|theme| theme.text != theme.background && theme.accent != theme.background)
        );
        assert_eq!(
            Theme::by_name("missing").accent,
            Theme::by_name("nord").accent
        );
        assert_ne!(
            Theme::by_name("nord").selected().fg,
            Theme::by_name("nord").selected().bg
        );
    }
}
