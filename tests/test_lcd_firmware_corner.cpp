// Execute the actual corner compositor against a pixel-recording display.
// g++ -std=c++17 tests/test_lcd_firmware_corner.cpp -o /tmp/pine-lcd-corner && /tmp/pine-lcd-corner
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <string>
#include <vector>
using std::max;
static int constrain(int value,int low,int high){return std::clamp(value,low,high);}
struct Arduino_GFX {
  int W,H,writes=0,scale=1,cursorX=0,cursorY=0;uint16_t ink=0;
  std::vector<uint16_t> pixels;std::vector<std::string> text;
  Arduino_GFX(int width,int height):W(width),H(height),pixels(W*H,0){}
  int width(){return W;}int height(){return H;}
  uint16_t color565(int r,int g,int b){return ((r>>3)<<11)|((g>>2)<<5)|(b>>3);}
  void fillRect(int x,int y,int w,int h,uint16_t color){
    assert(x>=0 && y>=0 && x+w<=W && y+h<=H);writes++;
    for(int row=0;row<h;row++)for(int col=0;col<w;col++)pixels[(y+row)*W+x+col]=color;
  }
  void fillScreen(uint16_t color){fillRect(0,0,W,H,color);}
  void fillRoundRect(int x,int y,int w,int h,int,uint16_t color){fillRect(x,y,w,h,color);}
  void drawRoundRect(int x,int y,int w,int h,int,uint16_t color){fillRect(x,y,w,1,color);fillRect(x,y+h-1,w,1,color);fillRect(x,y,1,h,color);fillRect(x+w-1,y,1,h,color);}
  void setTextSize(int value){scale=value;}void setTextColor(uint16_t value,uint16_t){ink=value;}
  void setCursor(int x,int y){cursorX=x;cursorY=y;}
  void print(const char* value){text.push_back(value);for(int i=0;value[i];i++)fillRect(cursorX+i*6*scale,cursorY,5*scale,7*scale,ink);}
  void draw16bitRGBBitmap(int x,int y,uint16_t* data,int w,int h){
    assert(x>=0 && y>=0 && x+w<=W && y+h<=H);writes++;
    for(int row=0;row<h;row++)for(int col=0;col<w;col++)pixels[(y+row)*W+x+col]=data[row*w+col];
  }
};
static Arduino_GFX* gfx=nullptr;
static bool gPineMode=true,gFlashing=false,gPineCornerDirty=true;
#include "../desktop/lcd-pine-corner.h"
static void verify(int W,int H,int block){
  Arduino_GFX display(W,H);gfx=&display;gPineCornerDirty=true;gPineMode=true;pineDrawCorner(false);
  assert(!pineRippleOutsideCorner(W/5+6,H/4+5,85)); // nearby tap must never corrupt the badge
  assert(!pineRippleOutsideCorner(W/5-1,H/4-1,85));
  assert(!pineRippleOutsideCorner(W/5+84,H/4-1,85)); // tangent ring touches last protected pixel
  assert(pineRippleOutsideCorner(W/5+85,H/4-1,85));
  assert(pineRippleOutsideCorner(W/5+64,H/4+64,85)); // diagonal disc misses the corner
  assert(pineRippleOutsideCorner(W-10,H-10,85));
  const auto badge=display.pixels;
  std::vector<uint16_t> tile(block*block);
  for(int y=0;y<H;y+=block)for(int x=0;x<W;x+=block){
    const int w=std::min(block,W-x),h=std::min(block,H-y);
    for(int row=0;row<h;row++)for(int col=0;col<w;col++)tile[row*w+col]=uint16_t((y+row)*W+x+col);
    pineBlitOutsideCorner(gfx,x,y,tile.data(),w,h);
    // The switch remains unchanged DURING every MCU callback, not just after a frame.
    for(int row=0;row<H/4;row++)for(int col=0;col<W/5;col++)assert(display.pixels[row*W+col]==badge[row*W+col]);
  }
  for(int y=0;y<H;y++)for(int x=0;x<W;x++)if(x>=W/5 || y>=H/4)assert(display.pixels[y*W+x]==uint16_t(y*W+x));
  int writes=display.writes;pineDrawCorner(false);assert(display.writes==writes); // no self-erasing redraw per frame
  pineFillOutsideCorner(gfx,0,0,W,20,1234);
  for(int y=0;y<H/4;y++)for(int x=0;x<W/5;x++)assert(display.pixels[y*W+x]==badge[y*W+x]);
  gPineMode=false;pineDrawCorner(false);assert(display.text[display.text.size()-2]=="PB");
  pineFillScreen(gfx,0);assert(gPineCornerDirty);pineDrawCorner(false);assert(!gPineCornerDirty);
  assert(display.text.back()=="SWAP");
}
int main(){
  verify(320,240,16);verify(320,240,32);verify(240,320,16);verify(320,240,24);
  std::cout<<"Corner pixels survive every native/scaled/straddling JPEG tile and letterbox clear; outside pixels and mode labels remain correct\n";
}
