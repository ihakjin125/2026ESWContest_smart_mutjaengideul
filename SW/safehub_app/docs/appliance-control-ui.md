# 가전 제어 / 수어 단축키 UI

기준: `feature/stt-tts-integration`의 `c87916c`.
학진이의 `feature/sign-shortcut-control` 코드는 읽어서 메시지 형식을 맞췄으며,
해당 브랜치를 병합하거나 변경하지 않았다.

## 사용

홈 → 공간별 상태 → **가전 · 수어 단축키**.

- 시뮬레이션: 거실 에어컨·조명 ON/OFF, 커튼 열기/닫기. 실제 명령 전송 없음.
- 시뮬레이션을 끄면 최근 허브 에어컨 명령을 표시한다. 실제 하드웨어 상태 확인이 아니다.
- 단축키는 수어 이름(직접 입력 또는 최근 결과 사용), 공간, 기기, 동작을 선택하여 등록한다.
- 현재 공간은 거실만 제공한다. 목록에서 수정·삭제·수동 단축키 테스트 가능.
- 같은 수어의 중복 신규 등록은 거부하며, 수정으로 교체한다.
- 등록은 앱 로컬에만 저장된다. 허브 등록 성공으로 표시하지 않는다.
- 인식된 수어를 UI에서 자동 실행하지 않는다. 허브와 UI에서 이중 토글되는 것을 방지한다.

## 확인된 기존 계약

구독: `safehub/control/livingroom/aircon/command`

```json
{"source":"sign_shortcut","action":"set_power","power_on":true}
```

중복 수신은 절대값을 다시 적용할 뿐 재토글하지 않는다.
기존 수어 번역 및 CSI 이벤트 구독은 유지한다.
수신 배치 전체를 처리하고 잘못된 메시지는 다른 메시지 처리를 막지 않는다.

학진이의 `ShortcutRegistrationHandler` 입력 형식은 UI에서 JSON으로 열람·복사할 수 있다.

```json
{"operation":"register","sign":"에어컨","room":"livingroom","device":"aircon","action":"toggle"}
```

```json
{"operation":"remove","sign":"에어컨"}
```

현재 학진이 ActionExecutor의 지원 범위는 거실 에어컨 toggle뿐이다.
조명/커튼 및 on/off 동작 JSON은 향후 확장용이며 현재는 UI 테스트 전용이다.
등록용 MQTT 토픽, 등록/삭제 응답, 초기 목록 조회, UI 버튼 명령을 허브 상태와 동기화하는
수신 경로는 학진이와 합의 후 연결해야 한다. 임의의 토픽으로 전송하지 않는다.
허브 재시작 시 에어컨 논리 상태가 False로 초기화되는 기존 동작도 추후 동기화가 필요하다.

## 저장

`$HOME/safehub_shortcuts/bindings.json` — 앱 사용자 HOME 아래 저장.
임시 파일 후 rename으로 교체하고 저장 실패 시 메모리 변경을 취소한다.
읽을 수 없거나 손상된 기존 파일은 덮어쓰지 않고 편집을 비활성화한다.
시뮬레이션 전원과 마지막 허브 명령은 저장하지 않는다.
앱 제거/데이터 초기화/앱 사용자 HOME 변경 시 보존은 보장하지 않는다.

## 검증

개발 컨테이너 `/repo_ui/SW/safehub_app`에서:

```sh
/opt/flutter-elinux-atlas/flutter/bin/dart format lib/core/appliance_controls.dart lib/services/shortcut_store.dart lib/ui/widgets/appliance_panel.dart lib/mqtt/mqtt_receiver.dart lib/ui/home_page.dart test/appliance_controls_test.dart test/appliance_panel_test.dart
/opt/flutter-elinux-atlas/flutter/bin/flutter test --no-pub
git diff --check
```

실기기에서는 1) 세 기기 시뮬레이션, 2) 등록/수정/삭제 후 앱 재시작,
3) 허브 command 수신 표시, 4) 중복 command에서 상태 유지,
5) MQTT 단절 표시, 6) 가전 페이지에서도 낙상/재난 오버레이,
7) 긴 수어 문장 스크롤, STT/TTS 및 카메라 회귀를 확인한다.

이 패치를 작성한 환경에는 Flutter/Dart SDK와 Atlas 플러그인이 없어
Flutter 테스트 및 실제 화면 렌더 검증은 실행하지 못했다.
