/**
 * Semantic design tokens for the mobile app.
 *
 * These tokens mirror the naming conventions used in web artifacts (index.css)
 * so that multi-artifact projects share a cohesive visual identity.
 *
 * Replace the placeholder values below with values that match the project's
 * brand. If a sibling web artifact exists, read its index.css and convert the
 * HSL values to hex so both artifacts use the same palette.
 *
 * To add dark mode, add a `dark` key with the same token names.
 * The useColors() hook will automatically pick it up.
 */

const colors = {
  light: {
    text: '#0F4C3A',
    tint: '#0F4C3A',
    background: '#F0F6F1',
    foreground: '#0F4C3A',
    card: '#FFFFFF',
    cardForeground: '#0F4C3A',
    primary: '#0F4C3A',
    primaryForeground: '#FFFFFF',
    secondary: '#CFE9D8',
    secondaryForeground: '#0F4C3A',
    muted: '#E8F1EB',
    mutedForeground: '#4A6B5E',
    accent: '#CFE9D8',
    accentForeground: '#0F4C3A',
    destructive: '#C42B1C',
    destructiveForeground: '#FFFFFF',
    border: '#D5E3DA',
    input: '#D5E3DA',
    leaf: '#2F8F5B',
    moss: '#4A6B5E',
    sprout: '#CFE9D8',
    amberBackground: '#FFE9B3',
    amberText: '#6B3F00',
    coralBackground: '#FFDAD3',
    coralText: '#8F1D14',
    strongCoral: '#C42B1C',
    track: '#E3EEE7',
    overlay: 'rgba(8, 38, 29, 0.32)',
  },

  radius: 24,
};

export default colors;
