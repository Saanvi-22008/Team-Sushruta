import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { ActivityIndicator, Image, Pressable, StyleSheet, Text, View } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTranslation } from 'react-i18next';
import { useColors } from '@/hooks/useColors';
import i18n from '@/i18n';

export type Language = 'en' | 'hi';
export type TextSize = 'normal' | 'large' | 'extraLarge';
export type ContactProfile = {
  clinicianName: string;
  clinicianPhone: string;
  emergencyPhone: string;
};

const PREF_LANGUAGE = 'sushruta.language';
const PREF_TEXT_SIZE = 'sushruta.textSize';
const PREF_CONTACTS = 'sushruta.contacts';

export const TEXT_SCALE: Record<TextSize, number> = {
  normal: 1,
  large: 1.15,
  extraLarge: 1.3,
};
export const DEFAULT_CONTACTS: ContactProfile = {
  clinicianName: '',
  clinicianPhone: '',
  emergencyPhone: '112',
};

type PreferencesValue = {
  loaded: boolean;
  language: Language | null;
  textSize: TextSize;
  contacts: ContactProfile;
  pickLanguage: (language: Language) => Promise<void>;
  chooseTextSize: (size: TextSize) => Promise<void>;
  saveContacts: (contacts: ContactProfile) => Promise<void>;
};

const PreferencesContext = createContext<PreferencesValue | null>(null);

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [loaded, setLoaded] = useState(false);
  const [language, setLanguage] = useState<Language | null>(null);
  const [textSize, setTextSize] = useState<TextSize>('normal');
  const [contacts, setContacts] = useState<ContactProfile>(DEFAULT_CONTACTS);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const [savedLanguage, savedTextSize, savedContacts] = await Promise.all([
          AsyncStorage.getItem(PREF_LANGUAGE),
          AsyncStorage.getItem(PREF_TEXT_SIZE),
          AsyncStorage.getItem(PREF_CONTACTS),
        ]);
        if (!active) return;
        if (savedLanguage === 'en' || savedLanguage === 'hi') {
          await i18n.changeLanguage(savedLanguage);
          setLanguage(savedLanguage);
        }
        if (savedTextSize === 'normal' || savedTextSize === 'large' || savedTextSize === 'extraLarge') {
          setTextSize(savedTextSize);
        }
        if (savedContacts) {
          try {
            setContacts({ ...DEFAULT_CONTACTS, ...(JSON.parse(savedContacts) as Partial<ContactProfile>) });
          } catch {
            setContacts(DEFAULT_CONTACTS);
          }
        }
      } catch {
        // Storage problems must never block the app. Defaults are used.
      } finally {
        if (active) setLoaded(true);
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, []);

  const pickLanguage = useCallback(async (next: Language) => {
    await i18n.changeLanguage(next);
    setLanguage(next);
    try {
      await AsyncStorage.setItem(PREF_LANGUAGE, next);
    } catch {
      // Not remembered, but the choice still applies for this session.
    }
  }, []);

  const chooseTextSize = useCallback(async (next: TextSize) => {
    setTextSize(next);
    try {
      await AsyncStorage.setItem(PREF_TEXT_SIZE, next);
    } catch {
      // Not remembered, but the choice still applies for this session.
    }
  }, []);

  const saveContacts = useCallback(async (next: ContactProfile) => {
    setContacts(next);
    try {
      await AsyncStorage.setItem(PREF_CONTACTS, JSON.stringify(next));
    } catch {
      // Not remembered, but the choice still applies for this session.
    }
  }, []);

  const value = useMemo(
    () => ({ loaded, language, textSize, contacts, pickLanguage, chooseTextSize, saveContacts }),
    [loaded, language, textSize, contacts, pickLanguage, chooseTextSize, saveContacts],
  );
  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}

export function usePreferences(): PreferencesValue {
  const value = useContext(PreferencesContext);
  if (!value) throw new Error('usePreferences must be used inside PreferencesProvider');
  return value;
}

/** Shows the loading spinner, then the first-launch language choice, then the app. */
export function PreferencesGate({ children }: { children: ReactNode }) {
  const { loaded, language, pickLanguage } = usePreferences();
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const { t } = useTranslation();
  const topInset = insets.top || 40;
  const bottomInset = insets.bottom || 20;

  if (!loaded) {
    return (
      <View style={[styles.centered, { backgroundColor: colors.background, paddingTop: topInset }]}>
        <ActivityIndicator color={colors.primary} size="large" />
      </View>
    );
  }

  if (!language) {
    return (
      <View style={[styles.languageScreen, { backgroundColor: colors.background, paddingTop: topInset + 20, paddingBottom: bottomInset + 24 }]}>
        <Image source={require('../assets/images/sushruta-mark.png')} style={styles.languageMark} resizeMode="contain" />
        <Text style={[styles.languageTitle, { color: colors.primary, fontFamily: 'AtkinsonHyperlegible_700Bold' }]}>{t('brand')}</Text>
        <Text style={[styles.languageIntro, { fontFamily: 'AtkinsonHyperlegible_400Regular', color: colors.moss }]}>{t('chooseLanguage')}</Text>
        <Text style={[styles.languageHint, { fontFamily: 'AtkinsonHyperlegible_400Regular', color: colors.moss }]}>{t('chooseLanguageHint')}</Text>
        <View style={styles.languageChoices}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="हिन्दी"
            testID="choose-hindi"
            onPress={() => void pickLanguage('hi')}
            style={({ pressed }) => [styles.languageChoice, { backgroundColor: colors.primary }, pressed && styles.pressed]}
          >
            <Text style={[styles.choiceHindi, { color: colors.primaryForeground, fontFamily: 'NotoSansDevanagari_700Bold' }]}>हिन्दी</Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="English"
            testID="choose-english"
            onPress={() => void pickLanguage('en')}
            style={({ pressed }) => [styles.languageChoice, { backgroundColor: colors.card, borderColor: colors.primary, borderWidth: 2 }, pressed && styles.pressed]}
          >
            <Text style={[styles.choiceEnglish, { color: colors.primary, fontFamily: 'AtkinsonHyperlegible_700Bold' }]}>English</Text>
          </Pressable>
        </View>
        <Text style={[styles.disclaimer, { fontFamily: 'AtkinsonHyperlegible_400Regular', color: colors.moss }]}>{t('disclaimer')}</Text>
      </View>
    );
  }

  return <>{children}</>;
}

const styles = StyleSheet.create({
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 28 },
  languageScreen: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 25, gap: 10 },
  languageMark: { width: 100, height: 115 },
  languageTitle: { fontSize: 30, lineHeight: 38 },
  languageIntro: { fontSize: 23, lineHeight: 32, textAlign: 'center' },
  languageHint: { fontSize: 17, lineHeight: 25, textAlign: 'center', marginBottom: 12 },
  languageChoices: { width: '100%', gap: 14, marginTop: 7 },
  languageChoice: { minHeight: 68, width: '100%', alignItems: 'center', justifyContent: 'center', borderRadius: 34 },
  choiceHindi: { fontSize: 24, lineHeight: 36 },
  choiceEnglish: { fontSize: 22 },
  disclaimer: { fontSize: 15, lineHeight: 23, textAlign: 'center', marginTop: 20 },
  pressed: { opacity: 0.78 },
});
