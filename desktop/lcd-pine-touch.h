// Additive Pine touch controller; compiled into the isolated Quanta sketch.
// Capture gestures until release so a swipe cannot also press a hidden button.
static bool gPineContact=false, gPineCapture=false, gPineWakeConsumed=false;
static uint32_t gPineTouchAt=0;
static int16_t gPineStartX=0,gPineStartY=0,gPineEndX=0,gPineEndY=0;
static void pineEvent(const String& value){ pushEvent(value); Serial.println("QEVT "+value); }
static void pineView(bool mode, bool remember, bool saver=false){
  gPineMode=mode; gPineSaver=saver; if(remember) pineRemember();
  gPineCornerDirty=true;
  gMenuOpen=false; gotContent=false; gLastHostMs=0; gGalFrame=0; gCacheIdx=0;
  pineEvent(String("PINEMODE ")+(gPineMode?"pine":"avatar"));
}
static String pineTouchDiagnostic(){
  String result=" raw "+String(gTouchRawX)+" "+String(gTouchRawY);
  #if defined(QUANTA_TOUCH_XPT2046)
  result+=" cal="+String(gCal.valid?1:0)+" rot="+String(gfx->getRotation());
  #endif
  return result;
}
static void pineSaver(bool enabled){
  pineView(!enabled,false,enabled);
  if(!enabled){gPineLastInput=millis(); pineEvent("PINEWAKE");}
}
static void pineIdle(){
  if(gPineMode && !gPineSaver && gPineIdleSeconds && (uint32_t)(millis()-gPineLastInput)>=gPineIdleSeconds*1000){
    pineSaver(true); pineEvent("PINESAVER 1");
  }
}
static bool pineTouch(bool down,int16_t x,int16_t y){
  if(down){
    gPineLastInput=millis();
    if(!gPineContact){
      gPineContact=true; gPineStartX=x;gPineStartY=y;gPineTouchAt=millis();
      gPineCapture=pineActive() || gPineSaver || y<40 || (x<gfx->width()/5 && y<gfx->height()/4);
      gPineWakeConsumed=gPineSaver;
      if(gPineSaver) pineSaver(false);
      if(gPineCapture) touchCount++;
    }
    gPineEndX=x;gPineEndY=y;
    return gPineCapture;
  }
  if(!gPineContact) return false;
  gPineContact=false;
  if(!gPineCapture) return false;
  gPineCapture=false;
  if(gPineWakeConsumed){gPineWakeConsumed=false;return true;}
  int dx=gPineEndX-gPineStartX,dy=gPineEndY-gPineStartY;
  uint32_t held=millis()-gPineTouchAt;
  if(gPineStartY<40 && dy>=32 && abs(dx)<90 && held<1600){
    if(!gPineMode) pineView(true,false);
    pineEvent("SWIPE down "+String(gPineEndX)+" "+String(gPineEndY));
  } else if(pineActive() && dy<=-32 && abs(dx)<90 && held<1600){
    pineEvent("SWIPE up "+String(gPineEndX)+" "+String(gPineEndY));
  } else if(abs(dx)<22 && abs(dy)<22 && held<1200){
    if(gPineStartX<gfx->width()/5 && gPineStartY<gfx->height()/4){
      pineView(!gPineMode,true); // explicit corner choice survives reboot
      pineEvent("PINECORNER "+String(gPineStartX)+" "+String(gPineStartY)+pineTouchDiagnostic());
    } else if(pineActive()){
      pineEvent("TOUCH tap "+String(gPineEndX)+" "+String(gPineEndY)+pineTouchDiagnostic());
    } else if(!gotContent && gPineStartY<30){
      gMenuOpen=true;gMenuOpenedMs=millis();drawMenu(); // original Quanta menu remains available
    }
  }
  return true;
}
