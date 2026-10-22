import { useState } from 'react';
import { ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Feather, MaterialCommunityIcons } from '@expo/vector-icons';
import Svg, { Circle, Polyline } from 'react-native-svg';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useColors } from '@/hooks/useColors';
import { TEXT_SCALE, usePreferences } from '@/context/Preferences';
import { getHistory, getTrend, type HistoryPoint } from '@/lib/apollo';

type Metric = 'ph' | 'skin_temp_c' | 'moisture_pct';

function formatDate(value: string | null, locale: string): string {
  if (!value) return '';
  return new Date(value).toLocaleString(locale, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function LineChart({ points, metric, color, trackColor }: { points: HistoryPoint[]; metric: Metric; color: string; trackColor: string }) {
  const [width, setWidth] = useState(0);
  const height = 84;
  const values = points.map((p) => p[metric]);
  const present = values.filter((v): v is number => v !== null);
  if (present.length < 2) return <View style={{ height }} />;
  const min = Math.min(...present);
  const max = Math.max(...present);
  const span = max - min || 1;
  const pad = 8;
  const step = (width - pad * 2) / Math.max(values.length - 1, 1);
  const coords = values
    .map((v, i) => (v === null ? null : `${pad + i * step},${pad + (1 - (v - min) / span) * (height - pad * 2)}`))
    .filter((c): c is string => c !== null);
  const last = coords[coords.length - 1]?.split(',').map(Number) ?? [0, 0];
  return (
    <View onLayout={(e) => setWidth(e.nativeEvent.layout.width)} style={{ height, backgroundColor: trackColor, borderRadius: 14 }}>
      {width > 0 && (
        <Svg width={width} height={height}>
          <Polyline points={coords.join(' ')} fill="none" stroke={color} strokeWidth={3} strokeLinejoin="round" strokeLinecap="round" />
          <Circle cx={last[0]} cy={last[1]} r={5} fill={color} />
        </Svg>
      )}
    </View>
  );
}

export default function HistoryScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const { t, i18n } = useTranslation();
  const { language: storedLanguage, textSize } = usePreferences();
  const language = storedLanguage ?? 'en';
  const scale = TEXT_SCALE[textSize];
  const regular = language === 'hi' ? 'NotoSansDevanagari_400Regular' : 'AtkinsonHyperlegible_400Regular';
  const bold = language === 'hi' ? 'NotoSansDevanagari_700Bold' : 'AtkinsonHyperlegible_700Bold';
  const topInset = Platform.OS === 'web' ? 24 : insets.top;

  const history = useQuery({ queryKey: ['history'], queryFn: () => getHistory(60), refetchInterval: 30_000, retry: 2 });
  const trend = useQuery({ queryKey: ['trend'], queryFn: getTrend, refetchInterval: 30_000, retry: 1 });

  const body = { fontFamily: regular, fontSize: 18 * scale, lineHeight: (language === 'hi' ? 30 : 26) * scale };
  const small = { fontFamily: regular, fontSize: 15 * scale, lineHeight: (language === 'hi' ? 25 : 21) * scale };
  const card = { backgroundColor: colors.card, borderColor: colors.border };

  const data = history.data;
  const trendData = trend.data;
  const trendTone =
    trendData?.level === 'rising'
      ? { bg: colors.coralBackground, fg: colors.coralText }
      : trendData?.level === 'watch'
        ? { bg: colors.amberBackground, fg: colors.amberText }
        : { bg: colors.sprout, fg: colors.primary };

  const charts: { metric: Metric; label: string; color: string }[] = [
    { metric: 'ph', label: t('historyChartPh'), color: colors.primary },
    { metric: 'skin_temp_c', label: t('historyChartTemp'), color: colors.strongCoral },
    { metric: 'moisture_pct', label: t('historyChartMoisture'), color: colors.leaf },
  ];

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={[styles.content, { paddingTop: topInset + 10 }]}
      showsVerticalScrollIndicator={false}
    >
      <Text accessibilityRole="header" style={{ fontFamily: bold, color: colors.primary, fontSize: 28 * scale, lineHeight: (language === 'hi' ? 42 : 34) * scale }}>
        {t('historyTitle')}
      </Text>
      <Text style={[small, { color: colors.moss }]}>{t('historySubtitle')}</Text>

      {history.isPending && <ActivityIndicator color={colors.primary} />}
      {history.isError && (
        <View style={[styles.card, card]}>
          <Text style={[body, { color: colors.coralText }]}>{t('historyError')}</Text>
          <Pressable accessibilityRole="button" onPress={() => void history.refetch()} style={[styles.button, { backgroundColor: colors.primary }]}>
            <Text style={[styles.buttonText, { fontFamily: bold, color: colors.primaryForeground }]}>{t('retry')}</Text>
          </Pressable>
        </View>
      )}

      {data && data.total === 0 && <Text style={[body, { color: colors.moss }]}>{t('historyEmpty')}</Text>}

      {data && data.total > 0 && (
        <>
          <View style={[styles.card, card]}>
            <View style={styles.row}>
              <Feather name="database" size={22} color={colors.primary} />
              <Text style={[body, { color: colors.foreground, fontFamily: bold, flex: 1 }]}>{t('historyCount', { count: data.total })}</Text>
            </View>
            <Text style={[small, { color: colors.moss }]}>
              {t('historySince', { date: formatDate(data.first_ts, i18n.language) })} · {t('demoData')}
            </Text>
            <View style={styles.chipRow}>
              {Object.entries(data.status_counts).map(([key, count]) => (
                <View key={key} style={[styles.chip, { backgroundColor: key === 'see_doctor_today' ? colors.coralBackground : key === 'keep_watching' ? colors.amberBackground : colors.sprout }]}>
                  <Text style={[small, { fontFamily: bold, color: key === 'see_doctor_today' ? colors.coralText : key === 'keep_watching' ? colors.amberText : colors.primary }]}>
                    {count} · {t(`status.${key}`)}
                  </Text>
                </View>
              ))}
            </View>
            <Text style={[small, { color: colors.moss }]}>{t('historyStored')}</Text>
          </View>

          {charts.map((chart) => (
            <View key={chart.metric} style={[styles.card, card]}>
              <Text style={[small, { fontFamily: bold, color: colors.primary }]}>{chart.label}</Text>
              <LineChart points={data.points} metric={chart.metric} color={chart.color} trackColor={colors.track} />
            </View>
          ))}
        </>
      )}

      <View style={[styles.card, { backgroundColor: trendData?.available ? trendTone.bg : colors.card, borderColor: colors.border }]}>
        <View style={styles.row}>
          <MaterialCommunityIcons name="chart-timeline-variant" size={24} color={trendData?.available ? trendTone.fg : colors.primary} />
          <Text style={[body, { fontFamily: bold, color: trendData?.available ? trendTone.fg : colors.primary, flex: 1 }]}>{t('trendTitle')}</Text>
        </View>
        {trendData?.available ? (
          <Text style={[body, { color: trendTone.fg }]}>
            {trendData.level === 'rising' ? t('trendRising') : trendData.level === 'watch' ? t('trendWatch') : t('trendLow')}
          </Text>
        ) : trendData ? (
          <Text style={[body, { color: colors.moss }]}>{t('trendNotEnough', { need: trendData.need ?? 6, have: trendData.have ?? 0 })}</Text>
        ) : null}
        <Text style={[small, { color: colors.moss }]}>{t('trendHint')}</Text>
      </View>

      <Text style={[small, styles.footnote, { color: colors.moss }]}>{t('disclaimer')}</Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { paddingHorizontal: 20, paddingBottom: 28, gap: 14 },
  card: { borderRadius: 24, borderWidth: 1, padding: 16, gap: 10 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { minHeight: 40, borderRadius: 20, paddingHorizontal: 14, justifyContent: 'center' },
  button: { minHeight: 48, borderRadius: 26, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 22, alignSelf: 'flex-start' },
  buttonText: { fontSize: 17 },
  footnote: { textAlign: 'center' },
});
