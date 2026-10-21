import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Alert,
  Image,
  KeyboardAvoidingView,
  Linking,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Feather, MaterialCommunityIcons } from '@expo/vector-icons';
import * as Speech from 'expo-speech';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  getGetStatusQueryKey,
  useGetStatus,
  useSetSimulatorScenario,
  type ReadingStatus,
  type ScenarioRequestScenario,
} from '@workspace/api-client-react';
import { useColors } from '@/hooks/useColors';
import i18n from '@/i18n';

type Language = 'en' | 'hi';
type TextSize = 'normal' | 'large' | 'extraLarge';
type ContactProfile = {
  clinicianName: string;
  clinicianPhone: string;
  emergencyPhone: string;
};

const PREF_LANGUAGE = 'sushruta.language';
const PREF_TEXT_SIZE = 'sushruta.textSize';
const PREF_CONTACTS = 'sushruta.contacts';
const TEXT_SCALE: Record<TextSize, number> = {
  normal: 1,
  large: 1.15,
  extraLarge: 1.3,
};
const DEFAULT_CONTACTS: ContactProfile = {
  clinicianName: '',
  clinicianPhone: '',
  emergencyPhone: '112',
};
const SCENARIOS: ScenarioRequestScenario[] = [
  'healing',
  'early_infection',
  'heavy_exudate',
  'inflammation_spike',
  'sensor_dropout',
];

function formatMetric(value: number | null | undefined, decimals = 1): string {
  return typeof value === 'number' ? value.toFixed(decimals) : '—';
}

function phoneDigits(value: string): string {
  return value.replace(/[^\d+]/g, '');
}

function metricPosition(metric: 'ph' | 'temperature' | 'moisture', value?: number | null) {
  if (typeof value !== 'number') return 50;
  if (metric === 'ph') return Math.min(100, Math.max(0, (value / 14) * 100));
  if (metric === 'temperature') return Math.min(100, Math.max(0, ((value - 34) / 6) * 100));
  return Math.min(100, Math.max(0, value));
}

function timeAgo(t: (key: string, options?: Record<string, unknown>) => string, timestamp?: string) {
  if (!timestamp) return t('updatedJustNow');
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(timestamp).getTime()) / 60_000));
  if (minutes < 1) return t('updatedJustNow');
  return t('updatedMinutes', { count: minutes });
}

export default function HomeScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const topInset = Platform.OS === 'web' ? 67 : insets.top;
  const bottomInset = Platform.OS === 'web' ? 34 : insets.bottom;
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [language, setLanguage] = useState<Language | null>(null);
  const [textSize, setTextSize] = useState<TextSize>('normal');
  const [preferencesLoaded, setPreferencesLoaded] = useState(false);
  const [showTextSize, setShowTextSize] = useState(false);
  const [showScenarios, setShowScenarios] = useState(false);
  const [showContacts, setShowContacts] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [contactDraft, setContactDraft] = useState<ContactProfile>(DEFAULT_CONTACTS);
  const [contacts, setContacts] = useState<ContactProfile>(DEFAULT_CONTACTS);
  const [scenarioError, setScenarioError] = useState(false);

  const statusQuery = useGetStatus({
    query: {
      queryKey: getGetStatusQueryKey(),
      enabled: preferencesLoaded && language !== null,
      refetchInterval: 30_000,
      retry: 1,
    },
  });
  const scenarioMutation = useSetSimulatorScenario({
    mutation: {
      onSuccess: (data: ReadingStatus) => {
        setScenarioError(false);
        queryClient.setQueryData(getGetStatusQueryKey(), data);
        setShowScenarios(false);
      },
      onError: () => setScenarioError(true),
    },
  });

  useEffect(() => {
    let active = true;
    const loadPreferences = async () => {
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
            const parsed = JSON.parse(savedContacts) as Partial<ContactProfile>;
            setContacts({ ...DEFAULT_CONTACTS, ...parsed });
            setContactDraft({ ...DEFAULT_CONTACTS, ...parsed });
          } catch {
            setContacts(DEFAULT_CONTACTS);
          }
        }
      } finally {
        if (active) setPreferencesLoaded(true);
      }
    };
    void loadPreferences();
    return () => {
      active = false;
    };
  }, []);

  const scale = TEXT_SCALE[textSize];
  const regularFont = language === 'hi' ? 'NotoSansDevanagari_400Regular' : 'AtkinsonHyperlegible_400Regular';
  const boldFont = language === 'hi' ? 'NotoSansDevanagari_700Bold' : 'AtkinsonHyperlegible_700Bold';
  const status = statusQuery.data;
  const reading = status?.reading;
  const currentStatus = status?.status ?? 'keep_watching';
  const statusColors = useMemo(() => {
    if (currentStatus === 'see_doctor_today') {
      return {
        background: colors.coralBackground,
        foreground: colors.coralText,
        icon: colors.strongCoral,
        button: colors.strongCoral,
      };
    }
    if (currentStatus === 'keep_watching') {
      return {
        background: colors.amberBackground,
        foreground: colors.amberText,
        icon: colors.amberText,
        button: colors.primary,
      };
    }
    return {
      background: colors.sprout,
      foreground: colors.primary,
      icon: colors.leaf,
      button: colors.primary,
    };
  }, [colors, currentStatus]);

  const pickLanguage = useCallback(async (nextLanguage: Language) => {
    await AsyncStorage.setItem(PREF_LANGUAGE, nextLanguage);
    await i18n.changeLanguage(nextLanguage);
    setLanguage(nextLanguage);
  }, []);

  const chooseTextSize = useCallback(async (nextSize: TextSize) => {
    setTextSize(nextSize);
    await AsyncStorage.setItem(PREF_TEXT_SIZE, nextSize);
    setShowTextSize(false);
  }, []);

  const speakStatus = useCallback(async () => {
    if (speaking) {
      await Speech.stop();
      setSpeaking(false);
      return;
    }
    if (!status) return;
    const message = [
      t(`status.${status.status}`),
      t(`reason.${status.reason_code}`),
      t('todayReadings'),
      `${t('ph')}: ${formatMetric(reading?.ph)}`,
      `${t('temperature')}: ${formatMetric(reading?.skin_temp_c)} ${t('unitCelsius')}`,
      `${t('moisture')}: ${formatMetric(reading?.moisture_pct, 0)} ${t('unitPercent')}`,
    ].join('. ');
    setSpeaking(true);
    Speech.speak(message, {
      language: language === 'hi' ? 'hi-IN' : 'en-IN',
      onDone: () => setSpeaking(false),
      onStopped: () => setSpeaking(false),
      onError: () => setSpeaking(false),
    });
  }, [language, reading, speaking, status, t]);

  const openContacts = useCallback(() => {
    setContactDraft(contacts);
    setShowContacts(true);
  }, [contacts]);

  const saveContacts = useCallback(async () => {
    const clinicianPhone = phoneDigits(contactDraft.clinicianPhone);
    const emergencyPhone = phoneDigits(contactDraft.emergencyPhone);
    if (emergencyPhone.length < 3 || (clinicianPhone && clinicianPhone.length < 3)) {
      Alert.alert(t('contactTitle'), t('invalidPhone'));
      return;
    }
    const next = {
      ...contactDraft,
      clinicianPhone,
      emergencyPhone,
    };
    await AsyncStorage.setItem(PREF_CONTACTS, JSON.stringify(next));
    setContacts(next);
    setShowContacts(false);
  }, [contactDraft, t]);

  const callNumber = useCallback(async (phone: string) => {
    const value = phoneDigits(phone);
    if (value.length < 3) {
      openContacts();
      return;
    }
    const url = `tel:${value}`;
    const supported = await Linking.canOpenURL(url);
    if (supported) {
      await Linking.openURL(url);
    } else {
      Alert.alert(t('callClinician', { name: contacts.clinicianName || t('clinician') }), t('callUnavailable'));
    }
  }, [contacts.clinicianName, openContacts, t]);

  const shareReport = useCallback(async () => {
    if (!status) return;
    const message = [
      t('shareTitle'),
      `${t('shareStatus')}: ${t(`status.${status.status}`)}`,
      `${t('ph')}: ${formatMetric(reading?.ph)}`,
      `${t('temperature')}: ${formatMetric(reading?.skin_temp_c)} ${t('unitCelsius')}`,
      `${t('moisture')}: ${formatMetric(reading?.moisture_pct, 0)} ${t('unitPercent')}`,
      t('shareDisclaimer'),
    ].join('\n');
    await Share.share({ message });
  }, [reading, status, t]);

  const bodyStyle = {
    fontFamily: regularFont,
    fontSize: 18 * scale,
    lineHeight: (language === 'hi' ? 30 : 25) * scale,
    color: colors.foreground,
  } as const;
  const labelStyle = {
    fontFamily: boldFont,
    fontSize: 17 * scale,
    lineHeight: (language === 'hi' ? 30 : 23) * scale,
    color: colors.foreground,
  } as const;

  if (!preferencesLoaded) {
    return (
      <View style={[styles.centered, { backgroundColor: colors.background, paddingTop: topInset }]}>
        <ActivityIndicator color={colors.primary} size="large" />
        <Text style={[bodyStyle, styles.loadingText]}>{t('loading')}</Text>
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

  const statusIcon = currentStatus === 'see_doctor_today'
    ? 'stethoscope'
    : currentStatus === 'keep_watching'
      ? 'eye-outline'
      : 'check';
  const latestTimestamp = reading?.ts;
  const scenarioLabel = scenarioMutation.isPending
    ? t('loading')
    : scenarioError
      ? t('scenarioError')
      : t('demoData');

  return (
    <View style={[styles.page, { backgroundColor: colors.background }]}>
      <ScrollView
        contentContainerStyle={[
          styles.scrollContent,
          { paddingTop: topInset + 10, paddingBottom: Math.max(bottomInset, 20) + 22 },
        ]}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.header}>
          <View style={styles.brandRow}>
            <Image source={require('../assets/images/sushruta-mark.png')} style={styles.headerMark} resizeMode="contain" />
            <View style={styles.brandCopy}>
              <Text style={[styles.greeting, { fontFamily: regularFont, color: colors.moss, fontSize: 15 * scale, lineHeight: (language === 'hi' ? 25 : 22) * scale }]}>{t('greeting')}</Text>
              <Text style={[styles.brandName, { fontFamily: boldFont, color: colors.primary, fontSize: 22 * scale, lineHeight: (language === 'hi' ? 34 : 29) * scale }]}>{t('brand')}</Text>
            </View>
          </View>
          <View style={styles.headerActions}>
            <View style={[styles.languageToggle, { backgroundColor: colors.card, borderColor: colors.border }]}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={t('hindi')}
                accessibilityState={{ selected: language === 'hi' }}
                testID="language-hi"
                onPress={() => void pickLanguage('hi')}
                style={({ pressed }) => [
                  styles.languageToggleButton,
                  language === 'hi' && { backgroundColor: colors.primary },
                  pressed && styles.pressed,
                ]}
              >
                <Text style={[styles.languageToggleText, { fontFamily: language === 'hi' ? 'NotoSansDevanagari_700Bold' : regularFont, color: language === 'hi' ? colors.primaryForeground : colors.moss }]}>{t('hindi')}</Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={t('english')}
                accessibilityState={{ selected: language === 'en' }}
                testID="language-en"
                onPress={() => void pickLanguage('en')}
                style={({ pressed }) => [
                  styles.languageToggleButton,
                  language === 'en' && { backgroundColor: colors.primary },
                  pressed && styles.pressed,
                ]}
              >
                <Text style={[styles.languageToggleText, { fontFamily: boldFont, color: language === 'en' ? colors.primaryForeground : colors.moss }]}>{t('english')}</Text>
              </Pressable>
            </View>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={t('textSize')}
              testID="open-text-size"
              onPress={() => setShowTextSize(true)}
              style={({ pressed }) => [styles.iconButton, { backgroundColor: colors.card, borderColor: colors.border }, pressed && styles.pressed]}
            >
              <Text style={[styles.aa, { fontFamily: boldFont, color: colors.primary }]}>Aa</Text>
            </Pressable>
          </View>
        </View>

        <Pressable
          accessibilityRole="button"
          accessibilityLabel={t('aboutData')}
          testID="open-scenarios"
          onPress={() => setShowScenarios(true)}
          style={({ pressed }) => [styles.demoPill, { backgroundColor: colors.card }, pressed && styles.pressed]}
        >
          <MaterialCommunityIcons name="flask-outline" size={22} color={colors.moss} />
          <Text style={[styles.demoText, { fontFamily: boldFont, color: colors.moss, fontSize: 15 * scale }]}>{scenarioLabel}</Text>
          <View style={styles.updatedTime}>
            <Feather name="clock" size={18} color={colors.moss} />
            <Text style={[styles.updatedText, { fontFamily: regularFont, color: colors.moss, fontSize: 15 * scale }]}>
              {timeAgo(t, latestTimestamp)}
            </Text>
          </View>
        </Pressable>

        {statusQuery.isPending ? (
          <View style={[styles.loadingPanel, { backgroundColor: colors.card }]}>
            <ActivityIndicator color={colors.primary} />
            <Text style={[bodyStyle, styles.loadingPanelText]}>{t('loading')}</Text>
          </View>
        ) : statusQuery.isError ? (
          <View style={[styles.offlineCard, { backgroundColor: colors.card, borderColor: colors.border }]}>
            <MaterialCommunityIcons name="wifi-off" size={30} color={colors.moss} />
            <Text style={[labelStyle, styles.offlineTitle]}>{t('offlineTitle')}</Text>
            <Text style={[bodyStyle, styles.offlineBody]}>{t('offlineBody')}</Text>
            <Pressable
              accessibilityRole="button"
              testID="retry-readings"
              onPress={() => void statusQuery.refetch()}
              style={({ pressed }) => [styles.primaryButton, { backgroundColor: colors.primary }, pressed && styles.pressed]}
            >
              <Text style={[styles.buttonText, { fontFamily: boldFont, color: colors.primaryForeground, fontSize: 17 * scale }]}>{t('retry')}</Text>
            </Pressable>
          </View>
        ) : (
          <>
            <View style={[styles.hero, { backgroundColor: statusColors.background }]}>
              <View style={styles.heroTop}>
                <View style={[styles.statusMedallion, { backgroundColor: colors.leaf }]}>
                  <MaterialCommunityIcons name={statusIcon as never} size={36} color={colors.card} />
                </View>
                <Text
                  accessibilityRole="header"
                  style={[
                    styles.statusHeadline,
                    {
                      fontFamily: boldFont,
                      color: colors.primary,
                      fontSize: 27 * scale,
                      lineHeight: (language === 'hi' ? 42 : 34) * scale,
                    },
                  ]}
                >
                  {t(`status.${currentStatus}`)}
                </Text>
              </View>
              <Text
                style={[
                  styles.statusReason,
                  {
                    fontFamily: regularFont,
                    color: currentStatus === 'see_doctor_today' ? statusColors.foreground : colors.moss,
                    fontSize: 18 * scale,
                    lineHeight: (language === 'hi' ? 32 : 26) * scale,
                  },
                ]}
              >
                {t(`reason.${status?.reason_code ?? 'no_reading_yet'}`)}
              </Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={speaking ? t('stopReading') : t('readToMe')}
                testID="read-status-aloud"
                onPress={() => void speakStatus().catch(() => {
                  setSpeaking(false);
                  Alert.alert(t('readingCheck'), t('speakUnavailable'));
                })}
                style={({ pressed }) => [
                  styles.readButton,
                  { backgroundColor: colors.card, borderColor: colors.primary },
                  pressed && styles.pressed,
                ]}
              >
                <Feather name={speaking ? 'volume-x' : 'volume-2'} size={22} color={colors.primary} />
                <Text style={[styles.readButtonText, { fontFamily: boldFont, color: colors.primary, fontSize: 17 * scale }]}>
                  {speaking ? t('stopReading') : t('readToMe')}
                </Text>
              </Pressable>
            </View>

            {currentStatus === 'see_doctor_today' && (
              <View style={styles.actionsBlock}>
                <Pressable
                  accessibilityRole="button"
                  testID="call-clinician"
                  onPress={() => contacts.clinicianPhone
                    ? void callNumber(contacts.clinicianPhone)
                    : openContacts()}
                  style={({ pressed }) => [styles.primaryButton, { backgroundColor: colors.strongCoral }, pressed && styles.pressed]}
                >
                  <Feather name={contacts.clinicianPhone ? 'phone' : 'user-plus'} size={22} color={colors.primaryForeground} />
                  <Text style={[styles.buttonText, { fontFamily: boldFont, color: colors.primaryForeground, fontSize: 17 * scale }]}>
                    {contacts.clinicianPhone
                      ? t('callClinician', { name: contacts.clinicianName || t('clinician') })
                      : t('addClinician')}
                  </Text>
                </Pressable>
                <View style={styles.secondaryActions}>
                  <Pressable
                    accessibilityRole="button"
                    testID="share-report"
                    onPress={() => void shareReport()}
                    style={({ pressed }) => [styles.outlineButton, { borderColor: colors.primary, backgroundColor: colors.card }, pressed && styles.pressed]}
                  >
                    <Feather name="share-2" size={20} color={colors.primary} />
                    <Text style={[styles.outlineButtonText, { fontFamily: boldFont, color: colors.primary, fontSize: 15 * scale }]}>{t('shareReport')}</Text>
                  </Pressable>
                  <Pressable
                    accessibilityRole="button"
                    testID="call-emergency"
                    onPress={() => void callNumber(contacts.emergencyPhone)}
                    style={({ pressed }) => [styles.outlineButton, { borderColor: colors.primary, backgroundColor: colors.card }, pressed && styles.pressed]}
                  >
                    <Feather name="phone-call" size={20} color={colors.primary} />
                    <Text style={[styles.outlineButtonText, { fontFamily: boldFont, color: colors.primary, fontSize: 15 * scale }]}>{t('callEmergency', { number: contacts.emergencyPhone || '112' })}</Text>
                  </Pressable>
                </View>
              </View>
            )}

            <View style={[styles.readingsCard, { backgroundColor: colors.card }]}>
              <View style={styles.readingsHeader}>
                <Text style={[styles.readingsTitle, { fontFamily: boldFont, color: colors.moss, fontSize: 18 * scale }]}>{t('todayReadings')}</Text>
                <View style={styles.battery}>
                  <MaterialCommunityIcons name="battery-high" size={21} color={colors.leaf} />
                  <Text style={[styles.batteryText, { fontFamily: boldFont, color: colors.moss, fontSize: 15 * scale }]}>
                    {reading ? `${t('patchBattery')} ${reading.battery_pct}%` : t('patchBattery')}
                  </Text>
                </View>
              </View>
              <MetricRow
                icon="water-outline"
                label={t('ph')}
                value={formatMetric(reading?.ph)}
                chip={t(`metric.${status?.metric_status.ph ?? 'check'}`)}
                barPosition={metricPosition('ph', reading?.ph)}
                textScale={scale}
                fontFamily={regularFont}
                boldFont={boldFont}
                colors={colors}
                statusTone={status?.metric_status.ph === 'high' ? 'coral' : status?.metric_status.ph === 'check' ? 'amber' : 'green'}
              />
              <MetricRow
                icon="thermometer"
                label={t('temperature')}
                value={formatMetric(reading?.skin_temp_c)}
                unit={t('unitCelsius')}
                chip={t(`metric.${status?.metric_status.temperature ?? 'check'}`)}
                barPosition={metricPosition('temperature', reading?.skin_temp_c)}
                textScale={scale}
                fontFamily={regularFont}
                boldFont={boldFont}
                colors={colors}
                statusTone={status?.metric_status.temperature === 'warm' ? 'amber' : status?.metric_status.temperature === 'check' ? 'amber' : 'green'}
              />
              <MetricRow
                icon="water-percent"
                label={t('moisture')}
                value={formatMetric(reading?.moisture_pct, 0)}
                unit={t('unitPercent')}
                chip={t(`metric.${status?.metric_status.moisture ?? 'check'}`)}
                barPosition={metricPosition('moisture', reading?.moisture_pct)}
                textScale={scale}
                fontFamily={regularFont}
                boldFont={boldFont}
                colors={colors}
                statusTone={status?.metric_status.moisture === 'high' ? 'amber' : status?.metric_status.moisture === 'low' || status?.metric_status.moisture === 'check' ? 'amber' : 'green'}
                last
              />
            </View>
          </>
        )}

        <View style={styles.footer}>
          <View style={styles.footerLine}>
            <Feather name="shield" size={19} color={colors.moss} />
            <Text style={[styles.footerText, { fontFamily: regularFont, color: colors.moss, fontSize: 15 * scale, lineHeight: (language === 'hi' ? 27 : 21) * scale }]}>
              {t('disclaimer')}
            </Text>
          </View>
          <Text style={[styles.thresholdNote, { fontFamily: regularFont, color: colors.moss, fontSize: 15 * scale }]}>
            {t('thresholdNote')}
          </Text>
        </View>
      </ScrollView>

      <ChoiceModal
        visible={showTextSize}
        title={t('textSize')}
        onClose={() => setShowTextSize(false)}
        colors={colors}
        boldFont={boldFont}
        regularFont={regularFont}
      >
        {(['normal', 'large', 'extraLarge'] as const).map((size) => (
          <Pressable
            key={size}
            accessibilityRole="button"
            accessibilityState={{ selected: textSize === size }}
            testID={`text-size-${size}`}
            onPress={() => void chooseTextSize(size)}
            style={({ pressed }) => [
              styles.choiceRow,
              { borderColor: textSize === size ? colors.primary : colors.border },
              pressed && styles.pressed,
            ]}
          >
            <Text style={[styles.choiceText, { fontFamily: boldFont, color: colors.primary, fontSize: 17 * scale }]}>{t(size)}</Text>
            {textSize === size && <Feather name="check" size={22} color={colors.primary} />}
          </Pressable>
        ))}
      </ChoiceModal>

      <ChoiceModal
        visible={showScenarios}
        title={t('scenariosTitle')}
        subtitle={t('scenariosHint')}
        onClose={() => setShowScenarios(false)}
        colors={colors}
        boldFont={boldFont}
        regularFont={regularFont}
      >
        {SCENARIOS.map((scenario) => (
          <Pressable
            key={scenario}
            accessibilityRole="button"
            testID={`scenario-${scenario}`}
            disabled={scenarioMutation.isPending}
            onPress={() => {
              setScenarioError(false);
              scenarioMutation.mutate({ data: { scenario } });
            }}
            style={({ pressed }) => [
              styles.choiceRow,
              { borderColor: colors.border },
              pressed && styles.pressed,
              scenarioMutation.isPending && styles.disabled,
            ]}
          >
            <Text style={[styles.choiceText, { fontFamily: boldFont, color: colors.primary, fontSize: 17 * scale }]}>{t(`scenario.${scenario}`)}</Text>
            {scenarioMutation.variables?.data.scenario === scenario && scenarioMutation.isPending && <ActivityIndicator color={colors.primary} />}
          </Pressable>
        ))}
        {scenarioError && <Text style={[bodyStyle, styles.modalError, { color: colors.coralText }]}>{t('scenarioError')}</Text>}
      </ChoiceModal>

      <Modal
        visible={showContacts}
        transparent
        animationType="slide"
        onRequestClose={() => setShowContacts(false)}
      >
        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
          style={[styles.modalScrim, { backgroundColor: colors.overlay }]}
        >
          <View style={[styles.modalCard, { backgroundColor: colors.card, paddingBottom: Math.max(bottomInset, 18) + 10 }]}>
            <View style={styles.modalHeader}>
              <Text style={[styles.modalTitle, { fontFamily: boldFont, color: colors.primary, fontSize: 23 * scale }]}>{t('contactTitle')}</Text>
              <Pressable accessibilityRole="button" accessibilityLabel={t('cancel')} onPress={() => setShowContacts(false)} style={styles.closeButton}>
                <Feather name="x" size={24} color={colors.primary} />
              </Pressable>
            </View>
            <TextInput
              accessibilityLabel={t('clinicianName')}
              value={contactDraft.clinicianName}
              onChangeText={(value) => setContactDraft((current) => ({ ...current, clinicianName: value }))}
              placeholder={t('clinicianName')}
              placeholderTextColor={colors.moss}
              style={[styles.input, { borderColor: colors.border, color: colors.foreground, fontFamily: regularFont, fontSize: 17 * scale }]}
              returnKeyType="next"
            />
            <TextInput
              accessibilityLabel={t('clinicianPhone')}
              value={contactDraft.clinicianPhone}
              onChangeText={(value) => setContactDraft((current) => ({ ...current, clinicianPhone: value }))}
              placeholder={`${t('clinicianPhone')} · ${t('phoneHint')}`}
              placeholderTextColor={colors.moss}
              keyboardType="phone-pad"
              style={[styles.input, { borderColor: colors.border, color: colors.foreground, fontFamily: regularFont, fontSize: 17 * scale }]}
            />
            <TextInput
              accessibilityLabel={t('emergencyPhone')}
              value={contactDraft.emergencyPhone}
              onChangeText={(value) => setContactDraft((current) => ({ ...current, emergencyPhone: value }))}
              placeholder={t('emergencyPhone')}
              placeholderTextColor={colors.moss}
              keyboardType="phone-pad"
              style={[styles.input, { borderColor: colors.border, color: colors.foreground, fontFamily: regularFont, fontSize: 17 * scale }]}
            />
            <View style={styles.modalFooterActions}>
              <Pressable accessibilityRole="button" onPress={() => setShowContacts(false)} style={[styles.modalAction, { borderColor: colors.border }]}>
                <Text style={[styles.modalActionText, { color: colors.primary, fontFamily: boldFont, fontSize: 16 * scale }]}>{t('cancel')}</Text>
              </Pressable>
              <Pressable accessibilityRole="button" testID="save-contacts" onPress={() => void saveContacts()} style={[styles.modalAction, { backgroundColor: colors.primary, borderColor: colors.primary }]}>
                <Text style={[styles.modalActionText, { color: colors.primaryForeground, fontFamily: boldFont, fontSize: 16 * scale }]}>{t('save')}</Text>
              </Pressable>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </View>
  );
}

function MetricRow({
  icon,
  label,
  value,
  unit,
  chip,
  barPosition,
  textScale,
  fontFamily,
  boldFont,
  colors,
  statusTone,
  last = false,
}: {
  icon: keyof typeof MaterialCommunityIcons.glyphMap;
  label: string;
  value: string;
  unit?: string;
  chip: string;
  barPosition: number;
  textScale: number;
  fontFamily: string;
  boldFont: string;
  colors: ReturnType<typeof useColors>;
  statusTone: 'green' | 'amber' | 'coral';
  last?: boolean;
}) {
  const tone = statusTone === 'coral'
    ? { background: colors.coralBackground, foreground: colors.coralText, icon: 'alert-triangle' as const }
    : statusTone === 'amber'
      ? { background: colors.amberBackground, foreground: colors.amberText, icon: 'alert-triangle' as const }
      : { background: colors.sprout, foreground: colors.primary, icon: 'check-circle' as const };

  return (
    <View style={[styles.metricRow, !last && { borderBottomColor: colors.border, borderBottomWidth: StyleSheet.hairlineWidth }]}>
      <View style={styles.metricMain}>
        <View style={[styles.metricIcon, { backgroundColor: colors.sprout }]}>
          <MaterialCommunityIcons name={icon} size={24} color={colors.primary} />
        </View>
        <Text style={[styles.metricLabel, { fontFamily: boldFont, color: colors.primary, fontSize: 17 * textScale, lineHeight: 24 * textScale }]}>{label}</Text>
        <Text style={[styles.metricValue, { fontFamily: boldFont, color: colors.primary, fontSize: 25 * textScale }]}>
          {value}<Text style={[styles.metricUnit, { fontFamily, fontSize: 15 * textScale }]}>{unit ? ` ${unit}` : ''}</Text>
        </Text>
      </View>
      <View style={styles.metricDetails}>
        <View style={styles.rangeTrack}>
          <View style={[styles.rangePart, { backgroundColor: colors.amberBackground, flex: 1 }]} />
          <View style={[styles.rangePart, { backgroundColor: colors.sprout, flex: 1.2 }]} />
          <View style={[styles.rangePart, { backgroundColor: colors.coralBackground, flex: 1 }]} />
          <View style={[styles.rangeMarker, { left: `${barPosition}%`, borderColor: colors.primary, backgroundColor: colors.card }]} />
        </View>
        <View style={[styles.metricChip, { backgroundColor: tone.background }]}>
          <Feather name={tone.icon} size={15} color={tone.foreground} />
          <Text style={[styles.metricChipText, { fontFamily: boldFont, color: tone.foreground, fontSize: 15 * textScale }]}>{chip}</Text>
        </View>
      </View>
    </View>
  );
}

function ChoiceModal({
  visible,
  title,
  subtitle,
  onClose,
  children,
  colors,
  boldFont,
  regularFont,
}: {
  visible: boolean;
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  colors: ReturnType<typeof useColors>;
  boldFont: string;
  regularFont: string;
}) {
  const insets = useSafeAreaInsets();
  const { t } = useTranslation();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={[styles.modalScrim, { backgroundColor: colors.overlay }]}>
        <View style={[styles.modalCard, { backgroundColor: colors.card, paddingBottom: Math.max(insets.bottom, 18) + 10 }]}>
          <View style={styles.modalHeader}>
            <Text style={[styles.modalTitle, { fontFamily: boldFont, color: colors.primary }]}>{title}</Text>
            <Pressable accessibilityRole="button" accessibilityLabel={t('close')} onPress={onClose} style={styles.closeButton}>
              <Feather name="x" size={24} color={colors.primary} />
            </Pressable>
          </View>
          {subtitle && <Text style={[styles.modalSubtitle, { fontFamily: regularFont, color: colors.moss }]}>{subtitle}</Text>}
          <ScrollView keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>
            <View style={styles.choiceList}>{children}</View>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1 },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 28 },
  loadingText: { marginTop: 18, textAlign: 'center' },
  scrollContent: { paddingHorizontal: 20, gap: 16 },
  header: { minHeight: 70, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  brandRow: { flexDirection: 'row', alignItems: 'center', gap: 10, flexShrink: 1 },
  headerMark: { width: 42, height: 54 },
  brandCopy: { flexShrink: 1 },
  greeting: { lineHeight: 22 },
  brandName: { lineHeight: 28 },
  headerActions: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  languageToggle: { minHeight: 48, borderRadius: 28, borderWidth: 1, padding: 3, flexDirection: 'row', alignItems: 'center' },
  languageToggleButton: { minWidth: 50, minHeight: 42, paddingHorizontal: 9, borderRadius: 24, alignItems: 'center', justifyContent: 'center' },
  languageToggleText: { fontSize: 15, lineHeight: 22 },
  iconButton: { minWidth: 48, minHeight: 48, alignItems: 'center', justifyContent: 'center', borderRadius: 24, borderWidth: 1 },
  aa: { fontSize: 17 },
  demoPill: { minHeight: 48, borderRadius: 28, paddingHorizontal: 14, flexDirection: 'row', alignItems: 'center', gap: 8 },
  demoText: { flex: 1 },
  updatedTime: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  updatedText: { flexShrink: 0 },
  hero: { borderRadius: 30, padding: 22, gap: 15 },
  heroTop: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  statusMedallion: { width: 66, height: 66, borderRadius: 24, alignItems: 'center', justifyContent: 'center' },
  statusHeadline: { flex: 1 },
  statusReason: { marginTop: -3 },
  readButton: { minHeight: 56, borderRadius: 32, borderWidth: 2, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10, paddingHorizontal: 16 },
  readButtonText: { textAlign: 'center' },
  actionsBlock: { gap: 10 },
  primaryButton: { minHeight: 58, borderRadius: 32, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10, paddingHorizontal: 15 },
  buttonText: { textAlign: 'center', flexShrink: 1 },
  secondaryActions: { flexDirection: 'row', gap: 9 },
  outlineButton: { minHeight: 52, flex: 1, borderRadius: 28, borderWidth: 2, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 7, paddingHorizontal: 8 },
  outlineButtonText: { textAlign: 'center', flexShrink: 1 },
  readingsCard: { borderRadius: 28, paddingHorizontal: 17, paddingTop: 17, paddingBottom: 2 },
  readingsHeader: { minHeight: 35, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  readingsTitle: { flexShrink: 1 },
  battery: { flexDirection: 'row', alignItems: 'center', gap: 4, flexShrink: 0 },
  batteryText: { flexShrink: 1, textAlign: 'right' },
  metricRow: { paddingVertical: 15, gap: 10 },
  metricMain: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  metricIcon: { width: 45, height: 45, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  metricLabel: { flex: 1 },
  metricValue: { flexShrink: 0, textAlign: 'right' },
  metricUnit: { fontWeight: '400' },
  metricDetails: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingLeft: 55 },
  rangeTrack: { height: 13, borderRadius: 8, overflow: 'visible', flex: 1, flexDirection: 'row', position: 'relative' },
  rangePart: { height: 13 },
  rangeMarker: { position: 'absolute', top: -5, marginLeft: -9, width: 23, height: 23, borderRadius: 12, borderWidth: 3 },
  metricChip: { minHeight: 34, borderRadius: 18, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 4, paddingHorizontal: 10 },
  metricChipText: { textAlign: 'center' },
  footer: { gap: 7, paddingHorizontal: 4, paddingTop: 1 },
  footerLine: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  footerText: { flex: 1 },
  thresholdNote: { marginLeft: 27, lineHeight: 21 },
  loadingPanel: { minHeight: 180, borderRadius: 28, alignItems: 'center', justifyContent: 'center', gap: 16, padding: 24 },
  loadingPanelText: { textAlign: 'center' },
  offlineCard: { minHeight: 240, borderWidth: 1, borderRadius: 28, alignItems: 'center', justifyContent: 'center', gap: 13, padding: 22 },
  offlineTitle: { textAlign: 'center' },
  offlineBody: { textAlign: 'center' },
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
  modalScrim: { flex: 1, justifyContent: 'flex-end' },
  modalCard: { borderTopLeftRadius: 28, borderTopRightRadius: 28, paddingHorizontal: 22, paddingTop: 20, maxHeight: '88%', gap: 14 },
  modalHeader: { minHeight: 48, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  modalTitle: { fontSize: 22, lineHeight: 31, flex: 1 },
  modalSubtitle: { fontSize: 17, lineHeight: 26 },
  closeButton: { width: 48, height: 48, alignItems: 'center', justifyContent: 'center' },
  choiceList: { gap: 10, paddingBottom: 10 },
  choiceRow: { minHeight: 56, borderRadius: 20, borderWidth: 1.5, paddingHorizontal: 16, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  choiceText: { flex: 1, lineHeight: 25 },
  modalError: {},
  input: { minHeight: 54, borderWidth: 1, borderRadius: 16, paddingHorizontal: 14 },
  modalFooterActions: { flexDirection: 'row', gap: 10, marginTop: 4 },
  modalAction: { minHeight: 52, flex: 1, alignItems: 'center', justifyContent: 'center', borderRadius: 18, borderWidth: 1.5, paddingHorizontal: 10 },
  modalActionText: { textAlign: 'center' },
  pressed: { opacity: 0.78 },
  disabled: { opacity: 0.55 },
});
