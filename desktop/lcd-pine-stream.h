// Native binary JPEG frames on an independent, persistent, bounded TCP socket.
// Original Quanta HTTP/serial/gallery upload handlers are unchanged.
#ifndef QUANTA_NO_WIFI
#ifdef QUANTA_JPEG
static const uint32_t PINE_MAX_JPEG=24576;
static WiFiServer pineServer(3233);
static WiFiClient pineClient;
static uint8_t *pineJpeg=nullptr;
static uint8_t pineHeader[12];
static uint32_t pineHeaderN=0,pineLength=0,pineReceived=0,pineSequence=0,pineRxAt=0,pineLastByte=0;
static uint32_t pineBE32(const uint8_t* p){return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];}
static void pineStreamClose(){
  pineClient.stop(); if(pineJpeg){free(pineJpeg);pineJpeg=nullptr;}
  pineHeaderN=0;pineLength=0;pineReceived=0;
}
static void pineStream(){
  if(!pineClient.connected()){
    pineStreamClose();
    WiFiClient incoming=pineServer.accept();
    if(!incoming) return;
    pineClient=incoming;pineClient.setNoDelay(true);pineLastByte=millis();
    pineClient.println("PINEFRAME 2 id="+pineIdentity()+" maxjpg="+String(PINE_MAX_JPEG));
  }
  // Reject extra producers; never replace the active connection mid-frame.
  WiFiClient extra=pineServer.accept(); if(extra){extra.println("PINEFRAME busy");extra.stop();}
  if((pineHeaderN || pineLength) && millis()-pineLastByte>2500){pineStreamClose();return;}
  uint32_t budget=4096;
  while(budget && pineClient.available()){
    if(pineHeaderN<12){
      int n=pineClient.read(pineHeader+pineHeaderN,min((uint32_t)12-pineHeaderN,budget));
      if(n<=0)return;
      if(!pineHeaderN)pineRxAt=millis();
      pineHeaderN+=n;budget-=n;pineLastByte=millis();
      if(pineHeaderN<12)continue;
      pineLength=pineBE32(pineHeader+8);pineSequence=pineBE32(pineHeader+4);
      if(memcmp(pineHeader,"PJF1",4) || pineLength<10 || pineLength>PINE_MAX_JPEG){pineStreamClose();return;}
      if(!pineJpeg)pineJpeg=(uint8_t*)malloc(PINE_MAX_JPEG);
      if(!pineJpeg){pineClient.println("QERR memory");pineStreamClose();return;}
    }
    uint32_t take=min(pineLength-pineReceived,budget);
    int n=pineClient.read(pineJpeg+pineReceived,take);if(n<=0)return;
    pineReceived+=n;budget-=n;pineLastByte=millis();
    if(pineReceived==pineLength){
      uint32_t rx=millis()-pineRxAt;
      uint16_t w=0,h=0;TJpgDec.getJpgSize(&w,&h,pineJpeg,pineLength);
      if(!pineActive() || gSaving){pineClient.println("QSKIP mode seq="+String(pineSequence));}
      else if(w!=gfx->width() || h!=gfx->height() || pineJpeg[0]!=255 || pineJpeg[1]!=216 || pineJpeg[pineLength-2]!=255 || pineJpeg[pineLength-1]!=217){
        pineClient.println("QERR jpeg seq="+String(pineSequence));
      } else {
        drawJpegBuf(pineJpeg,pineLength);
        String ack="QACK img "+String(w)+"x"+String(h)+" seq="+String(pineSequence)+" dec="+String(gLastDecMs)+" draw="+String(gLastDrawMs)+" rx="+String(rx)+" heap "+String(ESP.getFreeHeap())+" via=stream";
        pineClient.println(ack);Serial.println(ack);
      }
      pineHeaderN=0;pineLength=0;pineReceived=0;return; // one draw per cooperative loop
    }
  }
}
#endif
#endif
