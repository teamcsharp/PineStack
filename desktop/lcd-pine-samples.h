// Sampling uses the CYD's separate bit-banged touch pins, never TFT writes.
// Gesture dispatch waits until JPEG drawing has finished to avoid reentrancy.
bool touchReadScreen(int16_t &sx,int16_t &sy);
struct PineTouchSample {int16_t x,y;bool down;};
static PineTouchSample gPineSamples[16];
static uint8_t gPineSampleRead=0,gPineSampleWrite=0;
static uint32_t gPineSampleAt=0;
static void pineSampleDuringJpeg(){
  #if defined(QUANTA_BOARD_CYD_2432S028R)
  if(!gPineSaver && (int32_t)(gPineLeaseUntil-millis())<=0) return;
  if((uint32_t)(millis()-gPineSampleAt)<20) return;
  gPineSampleAt=millis();
  int16_t x=0,y=0;bool down=touchReadScreen(x,y);
  uint8_t next=(gPineSampleWrite+1)&15;
  if(next==gPineSampleRead) gPineSampleRead=(gPineSampleRead+1)&15;
  gPineSamples[gPineSampleWrite]={x,y,down};gPineSampleWrite=next;
  #endif
}
