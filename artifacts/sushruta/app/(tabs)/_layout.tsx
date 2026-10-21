import { Feather } from '@expo/vector-icons';
import { Tabs } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { useColors } from '@/hooks/useColors';
import { usePreferences } from '@/context/Preferences';

export default function TabsLayout() {
  const colors = useColors();
  const { t } = useTranslation();
  const { language } = usePreferences();
  const font = language === 'hi' ? 'NotoSansDevanagari_700Bold' : 'AtkinsonHyperlegible_700Bold';

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.moss,
        tabBarLabelStyle: { fontFamily: font, fontSize: 15 },
        tabBarStyle: {
          backgroundColor: colors.card,
          borderTopColor: colors.border,
          minHeight: 64,
          paddingTop: 6,
        },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: t('tabHome'),
          tabBarAccessibilityLabel: t('tabHome'),
          tabBarIcon: ({ color }) => <Feather name="home" size={24} color={color} />,
        }}
      />
      <Tabs.Screen
        name="apollo"
        options={{
          title: t('tabApollo'),
          tabBarAccessibilityLabel: t('tabApollo'),
          tabBarIcon: ({ color }) => <Feather name="message-circle" size={24} color={color} />,
        }}
      />
    </Tabs>
  );
}
