import { SymbolView } from 'expo-symbols';
import { Tabs } from 'expo-router';

import { palette } from '@/constants/theme';

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: palette.bgElevated },
        headerTintColor: palette.ink,
        sceneStyle: { backgroundColor: palette.bg },
        tabBarStyle: {
          backgroundColor: palette.bgElevated,
          borderTopColor: palette.border,
        },
        tabBarActiveTintColor: palette.accent,
        tabBarInactiveTintColor: palette.muted,
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: "Soap's Shelf",
          headerShown: false,
          tabBarIcon: ({ color }) => (
            <SymbolView
              name={{ ios: 'books.vertical', android: 'menu_book', web: 'menu_book' }}
              tintColor={color}
              size={26}
            />
          ),
        }}
      />
      <Tabs.Screen
        name="compiler"
        options={{
          title: 'Compile',
          tabBarIcon: ({ color }) => (
            <SymbolView
              name={{ ios: 'arrow.down.doc', android: 'download', web: 'download' }}
              tintColor={color}
              size={26}
            />
          ),
        }}
      />
      <Tabs.Screen
        name="categories"
        options={{
          title: 'Categories',
          headerShown: false,
          tabBarIcon: ({ color }) => (
            <SymbolView
              name={{ ios: 'tag', android: 'sell', web: 'sell' }}
              tintColor={color}
              size={26}
            />
          ),
        }}
      />
    </Tabs>
  );
}
