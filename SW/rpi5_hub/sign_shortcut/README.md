\# Sign Shortcut Control



수어 인식 결과에 사용자가 등록한 스마트홈 기기 동작을 연결하기 위한

RPi5 수어 단축키 제어 프로토타입입니다.



현재 기존 RPi5 Hub 및 SafeHub UI와는 분리된 상태이며,

`SW/rpi5\_hub/sign\_shortcut/` 내부에서 독립적으로 구현 및 테스트합니다.





\## 현재 구현 기능



\- 수어 단축키 등록

\- 수어 단축키 변경

\- 수어 단축키 삭제

\- 인식된 수어를 등록된 기기 동작으로 변환

\- 거실 에어컨 ON/OFF Toggle 논리

\- Device Control MQTT 메시지 생성

\- MQTT publish 처리

\- 등록되지 않은 수어 무시

\- 지원하지 않는 기기 동작 실행 방지





\## 동작 예시



사용자가 다음 단축키를 등록합니다.



```text

에어컨

→ livingroom

→ aircon

→ toggle

