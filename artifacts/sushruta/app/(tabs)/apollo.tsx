import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Image,
  KeyboardAvoidingView,
  Linking,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { Feather, MaterialCommunityIcons } from '@expo/vector-icons';
import * as Speech from 'expo-speech';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { getGetStatusQueryKey, useGetStatus } from '@workspace/api-client-react';
import { useColors } from '@/hooks/useColors';
import { TEXT_SCALE, usePreferences } from '@/context/Preferences';
import { askApollo, getTinyFishActivity, type ApolloReply } from '@/lib/apollo';

type Message = {
  id: string;
  role: 'user' | 'apollo';
  text: string;
  reply?: ApolloReply;
  error?: boolean;
};

const CHIPS = ['chipNormal', 'chipInfected', 'chipDressing', 'chipWarm', 'chipPain', 'chipPus'] as const;
const TINYFISH_LOGO = require('../../assets/images/tinyfish-logo.png');
const DOCKER_LOGO = require('../../assets/images/docker-logo.png');

function stripMarkers(text: string): string {
  return text.replace(/\s*\[\d+\]/g, '');
}

function phoneDigits(value: string): string {
  return value.replace(/[^\d+]/g, '');
}

export default function ApolloScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const { t } = useTranslation();
  const { language: storedLanguage, textSize, contacts } = usePreferences();
  const language = storedLanguage ?? 'en';
  const scale = TEXT_SCALE[textSize];
  const regularFont = language === 'hi' ? 'NotoSansDevanagari_400Regular' : 'AtkinsonHyperlegible_400Regular';
  const boldFont = language === 'hi' ? 'NotoSansDevanagari_700Bold' : 'AtkinsonHyperlegible_700Bold';
  const topInset = Platform.OS === 'web' ? 24 : insets.top;

  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState(false);
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  const [showActivity, setShowActivity] = useState(false);
  const [showAbout, setShowAbout] = useState(false);
  const scrollRef = useRef<ScrollView>(null);

  const statusQuery = useGetStatus({ query: { queryKey: getGetStatusQueryKey() } });
  const activityQuery = useQuery({
    queryKey: ['tinyfish-activity'],
    queryFn: () => getTinyFishActivity(15),
    enabled: showActivity,
  });

  useEffect(() => {
    const timer = setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 60);
    return () => clearTimeout(timer);
  }, [messages, pending]);

  useEffect(() => () => void Speech.stop(), []);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || pending) return;
      setDraft('');
      const id = String(Date.now());
      setMessages((current) => [...current, { id, role: 'user', text: message }]);
      setPending(true);
      try {
        const reply = await askApollo(message, language);
        setMessages((current) => [...current, { id: `${id}a`, role: 'apollo', text: reply.answer, reply }]);
      } catch {
        setMessages((current) => [...current, { id: `${id}e`, role: 'apollo', text: t('apolloError'), error: true }]);
      } finally {
        setPending(false);
      }
    },
    [language, pending, t],
  );

  const listen = useCallback(
    async (id: string, text: string) => {
      if (speakingId === id) {
        await Speech.stop();
        setSpeakingId(null);
        return;
      }
      await Speech.stop();
      setSpeakingId(id);
      Speech.speak(stripMarkers(text), {
        language: language === 'hi' ? 'hi-IN' : 'en-IN',
        onDone: () => setSpeakingId(null),
        onStopped: () => setSpeakingId(null),
        onError: () => setSpeakingId(null),
      });
    },
    [language, speakingId],
  );

  const callEmergency = useCallback(async () => {
    const number = phoneDigits(contacts.emergencyPhone || '112');
    try {
      await Linking.openURL(`tel:${number}`);
    } catch {
      // Calls are not available on this device (for example in a web preview).
    }
  }, [contacts.emergencyPhone]);

  const status = statusQuery.data?.status;
  const statusTone =
    status === 'see_doctor_today'
      ? { bg: colors.coralBackground, fg: colors.coralText, icon: 'stethoscope' as const }
      : status === 'keep_watching'
        ? { bg: colors.amberBackground, fg: colors.amberText, icon: 'eye-outline' as const }
        : { bg: colors.sprout, fg: colors.primary, icon: 'check' as const };

  const body = { fontFamily: regularFont, fontSize: 18 * scale, lineHeight: (language === 'hi' ? 30 : 26) * scale };
  const small = { fontFamily: regularFont, fontSize: 15 * scale, lineHeight: (language === 'hi' ? 25 : 21) * scale };

  return (
    <KeyboardAvoidingView
      style={[styles.page, { backgroundColor: colors.background }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={[styles.top, { paddingTop: topInset + 10 }]}>
        <Text accessibilityRole="header" style={[styles.title, { fontFamily: boldFont, color: colors.primary, fontSize: 28 * scale, lineHeight: (language === 'hi' ? 42 : 34) * scale }]}>
          {t('apolloTitle')}
        </Text>
        <Text style={[small, { color: colors.moss }]}>{t('apolloSubtitle')}</Text>

        <Pressable
          accessibilityRole="button"
          accessibilityLabel={t('aboutApolloTitle')}
          testID="open-about-apollo"
          onPress={() => setShowAbout(true)}
          style={({ pressed }) => [styles.builtWith, { backgroundColor: colors.card, borderColor: colors.border }, pressed && styles.pressed]}
        >
          <Text style={[styles.builtWithText, { fontFamily: boldFont, color: colors.moss, fontSize: 15 * scale }]}>{t('builtWith')}</Text>
          <Image source={TINYFISH_LOGO} accessibilityLabel="TinyFish" style={styles.tinyfishLogo} resizeMode="contain" />
          <Image source={DOCKER_LOGO} accessibilityLabel="Docker" style={styles.dockerLogo} resizeMode="contain" />
        </Pressable>

        {status && (
          <View style={[styles.contextStrip, { backgroundColor: statusTone.bg }]}>
            <MaterialCommunityIcons name={statusTone.icon} size={24} color={statusTone.fg} />
            <Text style={[small, styles.contextText, { fontFamily: boldFont, color: statusTone.fg }]}>
              {t('currentStatus')}: {t(`status.${status}`)}
            </Text>
          </View>
        )}
      </View>

      <ScrollView
        ref={scrollRef}
        style={styles.messages}
        contentContainerStyle={styles.messagesContent}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        <View style={[styles.bubble, styles.apolloBubble, { backgroundColor: colors.card, borderColor: colors.border }]}>
          <Text style={[body, { color: colors.foreground }]}>{t('apolloGreeting')}</Text>
        </View>

        {messages.map((message) =>
          message.role === 'user' ? (
            <View key={message.id} style={[styles.bubble, styles.userBubble, { backgroundColor: colors.primary }]}>
              <Text style={[body, { color: colors.primaryForeground }]}>{message.text}</Text>
            </View>
          ) : (
            <View key={message.id} style={[styles.bubble, styles.apolloBubble, { backgroundColor: colors.card, borderColor: colors.border }]}>
              {message.reply?.needs_doctor && message.reply.escalation && (
                <View style={[styles.escalation, { backgroundColor: colors.coralBackground }]}>
                  <View style={styles.escalationRow}>
                    <Feather name="alert-triangle" size={22} color={colors.coralText} />
                    <Text style={[body, styles.escalationText, { color: colors.coralText, fontFamily: boldFont }]}>{message.reply.escalation}</Text>
                  </View>
                  <Pressable
                    accessibilityRole="button"
                    testID="apollo-call-emergency"
                    onPress={() => void callEmergency()}
                    style={({ pressed }) => [styles.callButton, { backgroundColor: colors.strongCoral }, pressed && styles.pressed]}
                  >
                    <Feather name="phone" size={20} color={colors.primaryForeground} />
                    <Text style={[styles.callText, { fontFamily: boldFont, color: colors.primaryForeground, fontSize: 17 * scale }]}>
                      {t('callNow', { number: contacts.emergencyPhone || '112' })}
                    </Text>
                  </Pressable>
                </View>
              )}

              <Text style={[body, { color: message.error ? colors.coralText : colors.foreground }]}>{message.text}</Text>

              {message.reply && message.reply.citations.length > 0 && (
                <View style={styles.sourcesBlock}>
                  <Text style={[small, { color: colors.moss, fontFamily: boldFont }]}>{t('sources')}</Text>
                  <View style={styles.chipWrap}>
                    {message.reply.citations.map((citation) => (
                      <Pressable
                        key={citation.n}
                        accessibilityRole={citation.url ? 'link' : 'text'}
                        accessibilityLabel={`${citation.n}. ${citation.title}, ${citation.domain}`}
                        disabled={!citation.url}
                        onPress={() => citation.url && void Linking.openURL(citation.url)}
                        style={({ pressed }) => [styles.sourceChip, { backgroundColor: colors.sprout }, pressed && styles.pressed]}
                      >
                        <Text style={[small, { color: colors.primary, fontFamily: boldFont }]} numberOfLines={1}>
                          [{citation.n}] {citation.url ? citation.domain : t('savedNote')}
                        </Text>
                      </Pressable>
                    ))}
                  </View>
                  {message.reply.citations[0]?.retrieved_at && (
                    <Text style={[small, { color: colors.moss }]}>
                      {t('retrievedAt', {
                        time: new Date(message.reply.citations[0].retrieved_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                      })}
                    </Text>
                  )}
                </View>
              )}

              {message.reply && (
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={t('activityTitle')}
                  testID="open-tinyfish-activity"
                  onPress={() => setShowActivity(true)}
                  style={({ pressed }) => [styles.guidanceRow, pressed && styles.pressed]}
                >
                  <Text style={[small, styles.guidanceText, { color: colors.moss }]}>
                    {message.reply.guidance.mode === 'live'
                      ? t('liveGuidance', { count: message.reply.guidance.domain_count })
                      : message.reply.guidance.mode === 'cached'
                        ? t('cachedGuidance')
                        : t('offlineGuidance')}
                  </Text>
                  {message.reply.guidance.mode !== 'offline' && (
                    <Image source={TINYFISH_LOGO} accessibilityLabel="TinyFish" style={styles.tinyfishSmall} resizeMode="contain" />
                  )}
                </Pressable>
              )}

              {!message.error && (
                <Pressable
                  accessibilityRole="button"
                  testID={`listen-${message.id}`}
                  onPress={() => void listen(message.id, message.text)}
                  style={({ pressed }) => [styles.listenButton, { borderColor: colors.primary }, pressed && styles.pressed]}
                >
                  <Feather name={speakingId === message.id ? 'volume-x' : 'volume-2'} size={20} color={colors.primary} />
                  <Text style={[styles.listenText, { fontFamily: boldFont, color: colors.primary, fontSize: 16 * scale }]}>
                    {speakingId === message.id ? t('stopListening') : t('listen')}
                  </Text>
                </Pressable>
              )}
            </View>
          ),
        )}

        {pending && (
          <View style={[styles.bubble, styles.apolloBubble, styles.pendingBubble, { backgroundColor: colors.card, borderColor: colors.border }]}>
            <ActivityIndicator color={colors.primary} />
            <Text style={[body, { color: colors.moss, flexShrink: 1 }]}>{t('asking')}</Text>
          </View>
        )}
      </ScrollView>

      <View style={[styles.bottom, { backgroundColor: colors.background, borderTopColor: colors.border }]}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipsRow} keyboardShouldPersistTaps="handled">
          {CHIPS.map((key) => (
            <Pressable
              key={key}
              accessibilityRole="button"
              testID={`chip-${key}`}
              disabled={pending}
              onPress={() => void send(t(key))}
              style={({ pressed }) => [styles.quickChip, { backgroundColor: colors.card, borderColor: colors.border }, pressed && styles.pressed, pending && styles.disabled]}
            >
              <Text style={[small, { color: colors.primary, fontFamily: boldFont }]}>{t(key)}</Text>
            </Pressable>
          ))}
        </ScrollView>
        <View style={styles.composer}>
          <TextInput
            accessibilityLabel={t('apolloPlaceholder')}
            testID="apollo-input"
            value={draft}
            onChangeText={setDraft}
            placeholder={t('apolloPlaceholder')}
            placeholderTextColor={colors.moss}
            maxLength={500}
            returnKeyType="send"
            onSubmitEditing={() => void send(draft)}
            style={[styles.input, { backgroundColor: colors.card, borderColor: colors.border, color: colors.foreground, fontFamily: regularFont, fontSize: 18 * scale }]}
          />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={t('send')}
            testID="apollo-send"
            disabled={pending || draft.trim().length === 0}
            onPress={() => void send(draft)}
            style={({ pressed }) => [
              styles.sendButton,
              { backgroundColor: colors.primary },
              (pending || draft.trim().length === 0) && styles.disabled,
              pressed && styles.pressed,
            ]}
          >
            <Feather name="send" size={24} color={colors.primaryForeground} />
          </Pressable>
        </View>
        <Text style={[small, styles.footnote, { color: colors.moss }]}>{t('disclaimer')}</Text>
      </View>

      <Sheet visible={showAbout} title={t('aboutApolloTitle')} onClose={() => setShowAbout(false)} colors={colors} boldFont={boldFont} closeLabel={t('close')} bottomInset={insets.bottom}>
        <View style={styles.aboutRow}>
          <Image source={TINYFISH_LOGO} accessibilityLabel="TinyFish" style={styles.tinyfishLogo} resizeMode="contain" />
          <Text style={[body, styles.aboutText, { color: colors.foreground }]}>{t('aboutTinyFish')}</Text>
        </View>
        <View style={styles.aboutRow}>
          <Image source={DOCKER_LOGO} accessibilityLabel="Docker" style={styles.dockerLogo} resizeMode="contain" />
          <Text style={[body, styles.aboutText, { color: colors.foreground }]}>{t('aboutDocker')}</Text>
        </View>
      </Sheet>

      <Sheet visible={showActivity} title={t('activityTitle')} onClose={() => setShowActivity(false)} colors={colors} boldFont={boldFont} closeLabel={t('close')} bottomInset={insets.bottom}>
        <View style={styles.poweredRow}>
          <Text style={[small, { color: colors.moss }]}>{t('poweredBy')}</Text>
          <Image source={TINYFISH_LOGO} accessibilityLabel="TinyFish" style={styles.tinyfishSmall} resizeMode="contain" />
        </View>
        <Text style={[small, { color: colors.moss }]}>{t('activityHint')}</Text>
        {activityQuery.isPending && showActivity ? (
          <ActivityIndicator color={colors.primary} />
        ) : (activityQuery.data ?? []).length === 0 ? (
          <Text style={[body, { color: colors.moss }]}>{t('activityEmpty')}</Text>
        ) : (
          (activityQuery.data ?? []).map((item, index) => (
            <View key={`${item.ts}-${index}`} style={[styles.activityItem, { borderColor: colors.border }]}>
              <Text style={[small, { color: colors.primary, fontFamily: boldFont }]}>
                {item.kind} · {item.status}
                {item.elapsed_ms ? ` · ${item.elapsed_ms} ms` : ''}
              </Text>
              <Text style={[small, { color: colors.foreground }]}>{item.query}</Text>
              {item.detail ? <Text style={[small, { color: colors.moss }]}>{item.detail}</Text> : null}
            </View>
          ))
        )}
      </Sheet>
    </KeyboardAvoidingView>
  );
}

function Sheet({
  visible,
  title,
  onClose,
  children,
  colors,
  boldFont,
  closeLabel,
  bottomInset,
}: {
  visible: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  colors: ReturnType<typeof useColors>;
  boldFont: string;
  closeLabel: string;
  bottomInset: number;
}) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={[styles.scrim, { backgroundColor: colors.overlay }]}>
        <View style={[styles.sheet, { backgroundColor: colors.card, paddingBottom: Math.max(bottomInset, 18) + 10 }]}>
          <View style={styles.sheetHeader}>
            <Text accessibilityRole="header" style={[styles.sheetTitle, { fontFamily: boldFont, color: colors.primary }]}>{title}</Text>
            <Pressable accessibilityRole="button" accessibilityLabel={closeLabel} onPress={onClose} style={styles.closeButton}>
              <Feather name="x" size={24} color={colors.primary} />
            </Pressable>
          </View>
          <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={styles.sheetBody}>
            {children}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1 },
  top: { paddingHorizontal: 20, gap: 8 },
  title: {},
  builtWith: { minHeight: 48, borderRadius: 28, borderWidth: 1, paddingHorizontal: 14, flexDirection: 'row', alignItems: 'center', gap: 12, alignSelf: 'flex-start' },
  builtWithText: {},
  tinyfishLogo: { width: 98, height: 22 },
  dockerLogo: { width: 26, height: 22 },
  tinyfishSmall: { width: 66, height: 15 },
  contextStrip: { minHeight: 48, borderRadius: 24, paddingHorizontal: 14, paddingVertical: 8, flexDirection: 'row', alignItems: 'center', gap: 10 },
  contextText: { flex: 1 },
  messages: { flex: 1 },
  messagesContent: { paddingHorizontal: 20, paddingVertical: 14, gap: 12 },
  bubble: { borderRadius: 24, padding: 16, gap: 12, maxWidth: '94%' },
  apolloBubble: { alignSelf: 'flex-start', borderWidth: 1 },
  userBubble: { alignSelf: 'flex-end' },
  pendingBubble: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  escalation: { borderRadius: 18, padding: 14, gap: 12 },
  escalationRow: { flexDirection: 'row', gap: 10, alignItems: 'flex-start' },
  escalationText: { flex: 1 },
  callButton: { minHeight: 52, borderRadius: 28, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10, paddingHorizontal: 14 },
  callText: { textAlign: 'center' },
  sourcesBlock: { gap: 6 },
  chipWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  sourceChip: { minHeight: 44, borderRadius: 22, paddingHorizontal: 14, alignItems: 'center', justifyContent: 'center', maxWidth: '100%' },
  guidanceRow: { minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  guidanceText: { flexShrink: 1 },
  listenButton: { minHeight: 48, alignSelf: 'flex-start', borderRadius: 26, borderWidth: 2, flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 16 },
  listenText: {},
  bottom: { borderTopWidth: StyleSheet.hairlineWidth, paddingTop: 10, paddingBottom: 8, gap: 8 },
  chipsRow: { paddingHorizontal: 20, gap: 8 },
  quickChip: { minHeight: 44, borderRadius: 22, borderWidth: 1, paddingHorizontal: 14, alignItems: 'center', justifyContent: 'center' },
  composer: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 20 },
  input: { flex: 1, minHeight: 56, borderRadius: 28, borderWidth: 1, paddingHorizontal: 18 },
  sendButton: { width: 56, height: 56, borderRadius: 28, alignItems: 'center', justifyContent: 'center' },
  footnote: { paddingHorizontal: 20, textAlign: 'center' },
  scrim: { flex: 1, justifyContent: 'flex-end' },
  sheet: { borderTopLeftRadius: 28, borderTopRightRadius: 28, paddingHorizontal: 22, paddingTop: 20, maxHeight: '88%', gap: 12 },
  sheetHeader: { minHeight: 48, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  sheetTitle: { flex: 1, fontSize: 22, lineHeight: 31 },
  sheetBody: { gap: 14, paddingBottom: 10 },
  closeButton: { width: 48, height: 48, alignItems: 'center', justifyContent: 'center' },
  aboutRow: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  aboutText: { flex: 1 },
  poweredRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  activityItem: { borderBottomWidth: StyleSheet.hairlineWidth, paddingBottom: 10, gap: 2 },
  pressed: { opacity: 0.78 },
  disabled: { opacity: 0.5 },
});
