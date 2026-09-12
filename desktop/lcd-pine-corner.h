// One owner for the native corner pixels. JPEGs (including SD avatars) cannot
// paint over this region between callbacks, so the switch never flashes away.
static bool gPineCornerReady=false,gPineCornerLastMode=false;
static int gPineCornerLastW=0,gPineCornerLastH=0;
static bool pineRippleOutsideCorner(int x,int y,int radius){
  int dx=max(0,x-(gfx->width()/5-1)),dy=max(0,y-(gfx->height()/4-1));
  return dx*dx+dy*dy>radius*radius;
}
static void pineFillScreen(Arduino_GFX* target,uint16_t color){
  gPineCornerDirty=true;target->fillScreen(color);
}
static void pineFillOutsideCorner(Arduino_GFX* target,int x,int y,int w,int h,uint16_t color){
  if(target!=gfx || gFlashing || x>=gfx->width()/5 || y>=gfx->height()/4){target->fillRect(x,y,w,h,color);return;}
  int cutW=constrain(gfx->width()/5-x,0,w),cutH=constrain(gfx->height()/4-y,0,h);
  if(cutH<h)target->fillRect(x,y+cutH,w,h-cutH,color);
  if(cutW<w && cutH)target->fillRect(x+cutW,y,w-cutW,cutH,color);
}
static void pineBlitOutsideCorner(Arduino_GFX* target,int x,int y,uint16_t* pixels,int w,int h){
  if(target!=gfx || gFlashing || x>=gfx->width()/5 || y>=gfx->height()/4){target->draw16bitRGBBitmap(x,y,pixels,w,h);return;}
  int cutW=constrain(gfx->width()/5-x,0,w),cutH=constrain(gfx->height()/4-y,0,h);
  if(cutH<h)target->draw16bitRGBBitmap(x,y+cutH,pixels+cutH*w,w,h-cutH);
  // Right-hand fragments retain the decoder's original row stride.
  if(cutW<w)for(int row=0;row<cutH;row++)target->draw16bitRGBBitmap(x+cutW,y+row,pixels+row*w+cutW,w-cutW,1);
}
static void pineDrawCorner(bool force){
  if(gFlashing)return;
  int W=gfx->width(),H=gfx->height();
  if(!force && !gPineCornerDirty && gPineCornerReady && gPineCornerLastMode==gPineMode && gPineCornerLastW==W && gPineCornerLastH==H)return;
  int x=4,y=4,w=W/5-8,h=H/4-12;
  if(w<20 || h<20)return;
  uint16_t header=gfx->color565(16,38,54),fill=gfx->color565(16,38,50);
  uint16_t outline=gfx->color565(161,222,192),ink=gfx->color565(237,255,242);
  gfx->fillRect(0,0,W/5,H/4,header);
  gfx->fillRoundRect(x,y,w,h,6,fill);gfx->drawRoundRect(x,y,w,h,6,outline);
  int scale=w>=32?2:1;
  gfx->setTextSize(scale);gfx->setTextColor(ink,fill);
  gfx->setCursor(x+(w-12*scale)/2,y+max(3,(h-24)/2-3));gfx->print(gPineMode?"AV":"PB");
  gfx->setTextSize(1);gfx->setCursor(x+(w-24)/2,y+h-12);gfx->print("SWAP");
  gPineCornerReady=true;gPineCornerDirty=false;gPineCornerLastMode=gPineMode;gPineCornerLastW=W;gPineCornerLastH=H;
}
