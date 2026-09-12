// Execute the actual firmware touch controller with only Arduino I/O mocked.
// g++ -std=c++17 tests/test_lcd_firmware_touch.cpp -o /tmp/pine-lcd-touch && /tmp/pine-lcd-touch
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>
struct String:std::string {
  using std::string::string;
  String(const std::string& s):std::string(s){}
  String(int value):std::string(std::to_string(value)){}
};
static uint32_t nowMs=0,gPineLeaseUntil=30000,gPineIdleSeconds=0,gPineLastInput=0;
static bool gPineMode=true,gPineSaver=false,remembered=true,gMenuOpen=false,gotContent=false;
static bool gPineCornerDirty=true;
static int16_t gTouchRawX=1000,gTouchRawY=2000;
static uint32_t gLastHostMs=0,gMenuOpenedMs=0;
static int gGalFrame=0,gCacheIdx=0,touchCount=0,rememberCalls=0;
static uint32_t millis(){return nowMs;}
static bool pineActive(){return gPineMode && (int32_t)(gPineLeaseUntil-millis())>0;}
static void pineRemember(){remembered=gPineMode;rememberCalls++;}
struct Display {int width(){return 320;}int height(){return 240;}} display;
static Display* gfx=&display;
static std::vector<std::string> events;
static void pushEvent(const String& value){events.push_back(value);}
struct SerialMock {void println(const String&) {}} Serial;
static void drawMenu(){}
#define QUANTA_BOARD_CYD_2432S028R 1
static bool hardwareDown=false;static int16_t hardwareX=0,hardwareY=0;
bool touchReadScreen(int16_t& x,int16_t& y){x=hardwareX;y=hardwareY;return hardwareDown;}
#include "../desktop/lcd-pine-samples.h"
#include "../desktop/lcd-pine-touch.h"
static void reset(){
  nowMs=0;gPineLeaseUntil=30000;gPineIdleSeconds=0;gPineLastInput=0;gPineMode=true;gPineSaver=false;
  gPineContact=false;gPineCapture=false;gPineWakeConsumed=false;remembered=true;rememberCalls=0;events.clear();
  gPineSampleRead=0;gPineSampleWrite=0;gPineSampleAt=0;
}
int main(){
  reset();
  assert(pineTouch(true,100,10));nowMs=80;assert(pineTouch(true,105,80));nowMs=100;assert(pineTouch(false,0,0));
  assert(events.size()==1 && events[0]=="SWIPE down 105 80");
  reset();
  pineTouch(true,10,10);nowMs=80;pineTouch(true,10,90);nowMs=100;pineTouch(false,0,0);
  assert(gPineMode && rememberCalls==0 && events.size()==1); // corner swipe is not a corner tap
  reset();
  pineTouch(true,100,100);assert(events.empty());nowMs=50;pineTouch(false,0,0);
  assert(events.size()==1 && events[0]=="TOUCH tap 100 100 raw 1000 2000");
  reset();
  pineTouch(true,10,10);nowMs=50;pineTouch(false,0,0);
  assert(!gPineMode && !remembered && rememberCalls==1 && events.size()==2);
  assert(events[1]=="PINECORNER 10 10 raw 1000 2000");
  reset();gPineMode=false;remembered=false;
  pineTouch(true,100,5);nowMs=120;pineTouch(true,100,80);nowMs=140;pineTouch(false,0,0);
  assert(gPineMode && !remembered && rememberCalls==0 && events.size()==2 && events[0]=="PINEMODE pine" && events[1]=="SWIPE down 100 80");
  reset();pineSaver(true);events.clear();
  pineTouch(true,170,205);nowMs=100;pineTouch(true,180,50);nowMs=150;pineTouch(false,0,0);
  assert(gPineMode && !gPineSaver && events.size()==2 && events[0]=="PINEMODE pine" && events[1]=="PINEWAKE");
  reset();gPineIdleSeconds=15;nowMs=14999;pineIdle();assert(!gPineSaver);
  gLastHostMs=nowMs;gPineLeaseUntil=60000; // frames and lease renewal do not count as interaction
  nowMs=15000;pineIdle();assert(gPineSaver && !gPineMode && remembered);auto count=events.size();pineIdle();assert(events.size()==count);
  reset();gPineIdleSeconds=15;gPineMode=false;nowMs=20000;pineIdle();assert(!gPineSaver && !gPineMode);
  reset();gPineIdleSeconds=15;nowMs=14000;pineTouch(true,100,100);nowMs=14100;pineTouch(false,0,0);nowMs=20000;pineIdle();assert(!gPineSaver);
  reset();pineTouch(true,160,160);nowMs=100;pineTouch(true,160,80);nowMs=130;pineTouch(false,0,0);
  assert(events.size()==1 && events[0]=="SWIPE up 160 80");
  reset();
  hardwareDown=true;hardwareX=110;hardwareY=5;nowMs=20;pineSampleDuringJpeg();
  hardwareY=50;nowMs=40;pineSampleDuringJpeg();hardwareY=95;nowMs=60;pineSampleDuringJpeg();
  hardwareDown=false;nowMs=80;pineSampleDuringJpeg();assert(events.empty()); // no gesture/TFT reentrancy while drawing
  nowMs=120;
  while(gPineSampleRead!=gPineSampleWrite){auto sample=gPineSamples[gPineSampleRead];gPineSampleRead=(gPineSampleRead+1)&15;pineTouch(sample.down,sample.x,sample.y);}
  assert(events.size()==1 && events[0]=="SWIPE down 110 95");
  std::cout<<"11 actual firmware gesture/idle scenarios passed, including an entire swipe buffered during one JPEG draw\n";
}
