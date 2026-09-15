import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:safehub_app/core/appliance_controls.dart';
import 'package:safehub_app/ui/widgets/appliance_panel.dart';

void main() {
  for (final size in [const Size(1280, 720), const Size(600, 800)]) {
    testWidgets('가전 화면 스크롤 및 상태 분리 $size', (tester) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final model = ApplianceControls();
      await tester.pumpWidget(MaterialApp(
          home: Scaffold(
              body: AppliancePanel(
        controls: model,
        connected: true,
        latestSign: '에어컨',
        loadShortcuts: false,
      ))));
      await tester.pump();
      expect(find.text('거실 기기 & 수어 단축키'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.tap(find.text('켜기').first);
      await tester.pump();
      expect(model.preview['aircon'], true);
      expect(model.hubAirconPower, isNull);
      await tester.tap(find.byType(SwitchListTile));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text('상태 미확인'), findsNWidgets(3));
      model.receiveCommand('safehub/control/livingroom/aircon/command',
          {'action': 'set_power', 'power_on': true});
      await tester.pumpWidget(MaterialApp(
          home: Scaffold(
              body: AppliancePanel(
        controls: model,
        connected: true,
        latestSign: '에어컨',
        loadShortcuts: false,
      ))));
      await tester.pump();
      expect(find.text('켜짐 · ON'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
}
