#include <LCD_I2C.h>           // LCD Display
#include <elapsedMillis.h>     // Convenient timers
#include <FastLED.h>           // LEDs
#include <ResponsiveAnalogRead.h> // Analog input smoother

#define SD_ChipSelectPin 40  //use digital pin 4 on arduino Uno, nano etc, or can use other pins
#include <TMRpcm.h>          //  also need to include this library...
#include <SPI.h>
TMRpcm tmrpcm;   // create an object for use in this sketch

// Voice generator - https://voicegenerator.io/
// Audio converter website:  https://audio.online-convert.com/convert-to-wav  
// 8 bit, 16kHz, mono, U8

// Need to print instructions:
/*
  Switch sport modes by pressing  all four score buttons at once
  Switch

*/

#define NOTE_B0  31
#define NOTE_C1  33
#define NOTE_CS1 35
#define NOTE_D1  37
#define NOTE_DS1 39
#define NOTE_E1  41
#define NOTE_F1  44
#define NOTE_FS1 46
#define NOTE_G1  49
#define NOTE_GS1 52
#define NOTE_A1  55
#define NOTE_AS1 58
#define NOTE_B1  62
#define NOTE_C2  65
#define NOTE_CS2 69
#define NOTE_D2  73
#define NOTE_DS2 78
#define NOTE_E2  82
#define NOTE_F2  87
#define NOTE_FS2 93
#define NOTE_G2  98
#define NOTE_GS2 104
#define NOTE_A2  110
#define NOTE_AS2 117
#define NOTE_B2  123
#define NOTE_C3  131
#define NOTE_CS3 139
#define NOTE_D3  147
#define NOTE_DS3 156
#define NOTE_E3  165
#define NOTE_F3  175
#define NOTE_FS3 185
#define NOTE_G3  196
#define NOTE_GS3 208
#define NOTE_A3  220
#define NOTE_AS3 233
#define NOTE_B3  247
#define NOTE_C4  262
#define NOTE_CS4 277
#define NOTE_D4  294
#define NOTE_DS4 311
#define NOTE_E4  330
#define NOTE_F4  349
#define NOTE_FS4 370
#define NOTE_G4  392
#define NOTE_GS4 415
#define NOTE_A4  440
#define NOTE_AS4 466
#define NOTE_B4  494
#define NOTE_C5  523
#define NOTE_CS5 554
#define NOTE_D5  587
#define NOTE_DS5 622
#define NOTE_E5  659
#define NOTE_F5  698
#define NOTE_FS5 740
#define NOTE_G5  784
#define NOTE_GS5 831
#define NOTE_A5  880
#define NOTE_AS5 932
#define NOTE_B5  988
#define NOTE_C6  1047
#define NOTE_CS6 1109
#define NOTE_D6  1175
#define NOTE_DS6 1245
#define NOTE_E6  1319
#define NOTE_F6  1397
#define NOTE_FS6 1480
#define NOTE_G6  1568
#define NOTE_GS6 1661
#define NOTE_A6  1760
#define NOTE_AS6 1865
#define NOTE_B6  1976
#define NOTE_C7  2093
#define NOTE_CS7 2217
#define NOTE_D7  2349
#define NOTE_DS7 2489
#define NOTE_E7  2637
#define NOTE_F7  2794
#define NOTE_FS7 2960
#define NOTE_G7  3136
#define NOTE_GS7 3322
#define NOTE_A7  3520
#define NOTE_AS7 3729
#define NOTE_B7  3951
#define NOTE_C8  4186
#define NOTE_CS8 4435
#define NOTE_D8  4699
#define NOTE_DS8 4978
#define REST      0

int melodyRickRoll[] = {
  // from https://github.com/robsoncouto/arduino-songs
  // Never Gonna Give You Up - Rick Astley
  // Score available at https://musescore.com/chlorondria_5/never-gonna-give-you-up_alto-sax
  // Arranged by Chlorondria

  NOTE_A4,16, NOTE_B4,16, NOTE_D5,16, NOTE_B4,16,
  NOTE_FS5,-8, NOTE_FS5,-8, NOTE_E5,-4, NOTE_A4,16, NOTE_B4,16, NOTE_D5,16, NOTE_B4,16,

  NOTE_E5,-8, NOTE_E5,-8, NOTE_D5,-8, NOTE_CS5,16, NOTE_B4,-8, NOTE_A4,16, NOTE_B4,16, NOTE_D5,16, NOTE_B4,16, //18
  NOTE_D5,4, NOTE_E5,8, NOTE_CS5,-8, NOTE_B4,16, NOTE_A4,8, NOTE_A4,8, NOTE_A4,8, 
  NOTE_E5,4, NOTE_D5,2,
};

int melodyGameOfThrones[] = {

  // Game of Thrones
  // Score available at https://musescore.com/user/8407786/scores/2156716

  NOTE_G4,8, NOTE_C4,8, NOTE_DS4,16, NOTE_F4,16, NOTE_G4,8, NOTE_C4,8, NOTE_DS4,16, NOTE_F4,16, //1
  NOTE_G4,8, NOTE_C4,8, NOTE_DS4,16, NOTE_F4,16, NOTE_G4,8, NOTE_C4,8, NOTE_DS4,16, NOTE_F4,16,
  NOTE_G4,8, NOTE_C4,8, NOTE_E4,16, NOTE_F4,16, NOTE_G4,8, NOTE_C4,8, NOTE_E4,16, NOTE_F4,16,
  NOTE_G4,8, NOTE_C4,8, NOTE_E4,16, NOTE_F4,16, NOTE_G4,8, NOTE_C4,8, NOTE_E4,16, NOTE_F4,16,
  NOTE_G4,-4, NOTE_C4,-4,//5

  NOTE_DS4,16, NOTE_F4,16, NOTE_G4,4, NOTE_C4,4, NOTE_DS4,16, NOTE_F4,16, //6
  NOTE_D4,-2, //7 and 8
  
};

#define BrightSliderPin A0
#define HomeSliderPin A1
#define AwaySliderPin A2

ResponsiveAnalogRead analogBright(BrightSliderPin, true, 0.001);
ResponsiveAnalogRead analogHome(HomeSliderPin, true, 0.001);
ResponsiveAnalogRead analogAway(AwaySliderPin, true, 0.001);

// Arduino pins
#define HomeUpPin 7
#define HomeDownPin 6
#define AwayUpPin 12
#define AwayDownPin 11
#define ResetPin 8
#define SpeakerOutPin 5

// Pins from the Pi
#define PiSparePin 44 // Pi "Spare"
#define PiPinHome 45 // Pi "Left" 
#define PiPinAway 47 // Pi "Home" 
#define PiPinHeartbeat 46 // Pi heartbeat of inference running
#define PiPinSurrenderHome 42 // Orange Skinny
#define PiPinSurrenderAway 43 // Yellow Skinny

// LED stuff
#define DATA_PIN 3
#define NUM_LEDS 252
CRGB leds[NUM_LEDS];  

bool digitTable [16][7] {
//A B  C  D  E  F  G <-- segment to turn on/off
{1, 1, 1, 1, 0, 1, 1}, // 0
{0, 0, 0, 1, 0, 1, 0}, // 1
{1, 0, 1, 1, 1, 0, 1}, // 2
{0, 0, 1, 1, 1, 1, 1}, // 3
{0, 1, 0, 1, 1, 1, 0}, // 4
{0, 1, 1, 0, 1, 1, 1}, // 5
{1, 1, 1, 0, 1, 1, 1}, // 6
{0, 0, 1, 1, 0, 1, 0}, // 7
{1, 1, 1, 1, 1, 1, 1}, // 8
{0, 1, 1, 1, 1, 1, 1}, // 9
{1, 1, 1, 1, 1, 1, 0}, // 10 = A
{1, 0, 0, 1, 1, 1, 1}, // 11 = d
{0, 0, 0, 0, 1, 0, 0}, // 12 = -
{1, 1, 1, 0, 1, 0, 1}, // 13 = E
//{1, 1, 0, 1, 0, 1, 1}, // 14 = U
//{1, 1, 1, 0, 0, 0, 1}, // 15 = C
{1, 0, 0, 0, 0, 1, 1}, // 14 = u
{1, 0, 0, 0, 1, 0, 1}, // 15 = c
};


// Globals
int homeScore = 0;
int awayScore = 0;
int currentBright = 10;
int currentHomeColor = 10;
int currentAwayColor = 10;
int delayManualChange = 500; // Time to wait before can increment manually again
elapsedMillis timeManualScoreChange;
elapsedMillis timePiChange;
int delayPiChange = 3000;
elapsedMillis timeSparePinOn;
bool raspiOn = 0;
bool firstTimePiOn = 1;
bool firstTimePiOff = 0;
elapsedMillis timeHeartbeat = 4000;
elapsedMillis timeSincePiConnected = 5000;
int piDeadAfter = 2000; // time after which the pi is "disconnected"
bool prevHeartbeatValue = 0;
long prevHeartbeatPeriod1 = 4000; // to keep track of the previous ones (long: signed + 32-bit)
long prevHeartbeatPeriod2 = 5000;
long heartbeatRange = 700; //ms
bool prevSparePinValue = 0;
bool blueBorderShowing = false;
bool gameWonFirstTime = true;
int justPlayedWinningTune = 0;
bool SDSuccess = true;
int sportMode = 0; // 0 = Volleyball.  1 = Tennis.  2 = ??
bool WAVMode = true; // true = play .wav files if SD card works.  False = beeps only
int volleyballScoreTo = 21; //15, 21, or 25, defaulting to 21

// Color slider ends: below HUE_WHITE_BELOW the digits are white, above HUE_RAINBOW_ABOVE they are a rainbow
#define HUE_WHITE_BELOW 10
#define HUE_RAINBOW_ABOVE 240

// State broadcast to the Raspberry Pi on Serial1 (TX1 = pin 18), one way: the Pi forwards it to the phone.
// The Arduino never waits on the Pi: a line is only written when the TX buffer has room for all of it,
// otherwise it is skipped and sent on a later loop. One line per change (at most every 100ms) and at
// least once a second:
//   $S,<home>,<away>,<sportMode>,<scoreTo>,<piOn>,<homeColor>,<awayColor>,<d0>,<d1>,<d2>,<d3>,<event>,<eventSeq>*<XOR>\r\n
// Colors: 0-255 = FastLED hue, 256 = white, 257 = rainbow. d0-d3 = digitTable index of the home tens,
// home ones, away tens and away ones digits as drawn (-1 = blank). XOR = hex XOR of the chars between $ and *.
#define PI_LINK_BAUD 38400
#define COLOR_WHITE 256
#define COLOR_RAINBOW 257
elapsedMillis timeSinceStateSent;
int shownDigits[4] = {-1, 0, -1, 0};
const char* lastEvent = "BOOT"; // HU/HD/AU/AD buttons, HP/AP Pi point, HC/AC cobra, RS reset, HW/AW won, MD sport mode, GT game-to, SM sound mode
byte eventSeq = 0;
char lastStateBody[64] = "";

//LCD 
LCD_I2C lcd(0x27); 
elapsedMillis LCDUpdate;
int LCDRefreshRate = delayManualChange - 10; //ms between updating LCD



void makeBorderBlue();
void UpdateDisplay();
void playASong(int melodyArray[], int tempo);
void playRickRoll();
void playGameOfThrones();
void noteEvent(const char* code);
void sendStateIfDue(bool force);

void setup() {
  
  Serial.begin(115200);
  Serial1.begin(PI_LINK_BAUD); // state broadcast to the Pi (see sendStateIfDue)

  FastLED.addLeds<NEOPIXEL, DATA_PIN> (leds, NUM_LEDS);
  FastLED.setBrightness(10);
  
  pinMode(HomeUpPin,    INPUT_PULLUP);
  pinMode(HomeDownPin,  INPUT_PULLUP);
  pinMode(AwayUpPin,    INPUT_PULLUP);
  pinMode(AwayDownPin,  INPUT_PULLUP);
  pinMode(ResetPin,     INPUT_PULLUP);
  
  //pinMode(PiSparePin, INPUT);
  pinMode(PiPinHome, INPUT);
  pinMode(PiPinAway, INPUT);
  pinMode(PiPinHeartbeat, INPUT);
  pinMode(PiPinSurrenderHome, INPUT);
  pinMode(PiPinSurrenderAway, INPUT);

  //SD and speaker
  tmrpcm.speakerPin = SpeakerOutPin;  //5,6,11 or 46 on Mega, 9 on Uno, Nano, etc
  tmrpcm.quality(1); // Set it to high quality (1)
  tmrpcm.setVolume(5); //set the volume 0 to 7.  0 is default.  
  pinMode(SpeakerOutPin, OUTPUT);
  if (!SD.begin(SD_ChipSelectPin)) {  // see if the card is present and can be initialized:
    Serial.println("SD fail");  
    SDSuccess = false;
  }
  else Serial.println("SD card working!!!");
  // Song names:
  /*
  Boot.wav

  PointHome/PointAway/SurrenderHome/SurrenderAway
  PiConnected/PiDisconnected
  TennisMode/VolleyballMode
  
  homeUp1/2/3  homeDown1/2/3  awayUp1/2/3 awayDown1/2/3
  Reset

  */

  //LCD
  lcd.begin();
  lcd.noBacklight();
//  lcd.backlight();

  tmrpcm.play("Boot.wav");
  delay(3500);
  Serial.println("Starting!!");

}



void loop() {

  analogBright.update();
  analogHome.update();
  analogAway.update();  
  pinMode(AwayDownPin, INPUT_PULLUP); 

  // Scores
  // Home Up
  if(!digitalRead(HomeUpPin) && timeManualScoreChange > delayManualChange)
  {
    homeScore = homeScore + 1; // increase score
    timeManualScoreChange = 0; // Reset timer
    noteEvent("HU");
    
      if (SDSuccess && WAVMode){
        if(homeScore%3==0)      tmrpcm.play("hUp1.wav");
        else if(homeScore%3==1) tmrpcm.play("hUp2.wav");
        else if(homeScore%3==2) tmrpcm.play("hUp3.wav");}
      else 
        tone(SpeakerOutPin, 100, 100);
    UpdateDisplay(); 
    Serial.println("Home up");
  }
  // Home Down
  if(!digitalRead(HomeDownPin) && timeManualScoreChange > delayManualChange)
  {
    homeScore = homeScore - 1; // decrease score
    if(homeScore < 0) homeScore = 0;
    timeManualScoreChange = 0; // Reset timer
    noteEvent("HD");
    UpdateDisplay(); 
    if (SDSuccess && WAVMode){
      if(homeScore%3==0)      tmrpcm.play("hDown1.wav");
        else if(homeScore%3==1) tmrpcm.play("hDown2.wav");
        else if(homeScore%3==2) tmrpcm.play("hDown3.wav");
      }
    else 
      tone(SpeakerOutPin, 100, 50);
    Serial.println("Home down");
  }
  // Away Up
  if(!digitalRead(AwayUpPin) && timeManualScoreChange > delayManualChange)
  {
    awayScore = awayScore + 1; // increase score
    timeManualScoreChange = 0; // Reset timer
    noteEvent("AU");
     
      if (SDSuccess && WAVMode){
        if(awayScore%3==0)      tmrpcm.play("aUp1.wav");
        else if(awayScore%3==1) tmrpcm.play("aUp2.wav");
        else if (awayScore%3==2) tmrpcm.play("aUp3.wav");}
      else 
        tone(SpeakerOutPin, 350, 100);
    UpdateDisplay();
    Serial.println("Away up");
  }
  // Away Down
  if(!digitalRead(AwayDownPin) && timeManualScoreChange > delayManualChange)
  {
    Serial.println(String(!digitalRead(AwayDownPin)));
    awayScore = awayScore - 1; // increase score
    if(awayScore < 0) awayScore = 0;
    timeManualScoreChange = 0; // Reset timer
    noteEvent("AD");
    UpdateDisplay(); 
   
    if (SDSuccess && WAVMode){
      if(awayScore%3==0)      tmrpcm.play("aDown1.wav");
        else if(awayScore%3==1) tmrpcm.play("aDown2.wav");
        else if (awayScore%3==2) tmrpcm.play("aDown3.wav");
      }
    else 
      tone(SpeakerOutPin, 75, 65);
    Serial.println("Away down1");
  }
  // Reset
  if(!digitalRead(ResetPin) && timeManualScoreChange > delayManualChange)
  {
    awayScore = 0; 
    homeScore = 0;
    gameWonFirstTime = 1;
    timeManualScoreChange = 0; // Reset timer
    noteEvent("RS");
    UpdateDisplay(); 
    if (SDSuccess && WAVMode )
      tmrpcm.play("Reset.wav");
    else 
      tone(SpeakerOutPin, 50, 65);
  }
  
  // Home Up from Pi
  if(digitalRead(PiPinHome) && timePiChange > delayPiChange && raspiOn)
  {
    homeScore = homeScore + 1; // increase score
    timePiChange = 0; // Reset timer
    noteEvent("HP");
    if(justPlayedWinningTune == 0) 
    {
      if (SDSuccess && WAVMode)
        tmrpcm.play("PtHm.wav");
      else 
        tone(SpeakerOutPin, 400, 200);
    }
    //if(justPlayedWinningTune == 0) tone(SpeakerOutPin, 300, 250);
    UpdateDisplay(); 
    Serial.println("Point Home");
  }
  // Away Up from Pi
  if(digitalRead(PiPinAway) && timePiChange > delayPiChange && raspiOn)
  {
    awayScore = awayScore + 1; // increase score
    timePiChange = 0; // Reset timer
    noteEvent("AP");
    
    //startPlayback(pointAwayAudio, sizeof(pointAwayAudio));
    //if(justPlayedWinningTune == 0) tone(SpeakerOutPin, 500, 250);
    if(justPlayedWinningTune == 0) 
    {
      if (SDSuccess && WAVMode)
        tmrpcm.play("PtAwy.wav");
      else 
        tone(SpeakerOutPin, 500, 200);
    }
    Serial.println("Point away");
    UpdateDisplay(); 
  }

  //Surrender Cobra Home from Pi (Home down)
  if(digitalRead(PiPinSurrenderHome) && timePiChange > delayPiChange && raspiOn)
  {
    homeScore = homeScore - 1; // decrease score
    if(homeScore < 0) homeScore = 0;
    timePiChange = 0; // Reset timer
    noteEvent("HC");
    UpdateDisplay(); 
    if (SDSuccess && WAVMode)
      tmrpcm.play("SurHo.wav");
    else 
      tone(SpeakerOutPin, 400, 300);
    Serial.println("Surrender Cobra Home");
  }
  // Surrender Cobra Away from Pi (Away Down)
  if(digitalRead(PiPinSurrenderAway) && timePiChange > delayPiChange && raspiOn)
  {
    awayScore = awayScore - 1; // decrease score
    if(awayScore < 0) awayScore = 0;
    timePiChange = 0; // Reset timer
    noteEvent("AC");
    UpdateDisplay(); 
    if (SDSuccess && WAVMode)
      tmrpcm.play("SurAw.wav");
    else 
      tone(SpeakerOutPin, 500, 300);
    Serial.println("Point away");
  }
  
  // Heartbeat stuff
  if(raspiOn && timeHeartbeat > 4000 && timeSincePiConnected > 7000)
  {
    // The pi is no longer processing frames 
      if(firstTimePiOff)
      {
        Serial.println("Pi disconnected damnit from timer");
        if (SDSuccess && WAVMode)
          tmrpcm.play("PiDis.wav");
        //else 
          //tone(SpeakerOutPin, 500, 300);
      }
      firstTimePiOff = 0;
      firstTimePiOn = 1;
      raspiOn = 0;
  }
  if(digitalRead(PiPinHeartbeat) != prevHeartbeatValue)
  {
    Serial.println("sup");
    // Must be SIGNED long: with unsigned, "prevHeartbeatPeriod1 - heartbeatRange" goes negative for any
    // period < 700ms and wraps to ~4 billion, so the periods never match and the Pi gets disconnected.
    long thisHeartbeatPeriod = (long)timeHeartbeat;
    Serial.println("thisPeriod:  " + String(thisHeartbeatPeriod));
    Serial.println("prevPeriod1: " + String(prevHeartbeatPeriod1));
    Serial.println("prevPeriod2: " + String(prevHeartbeatPeriod2));
    Serial.println("justWinning:" + String(justPlayedWinningTune));
    
    // Fixed by Antigravity: lowered threshold from 300ms to 75ms to support high-speed Pi execution (up to 13 FPS)
    // Also allow instant connection on boot if previous periods are still in initial uncalibrated state (>= 3000ms)
    bool periodsMatch = (prevHeartbeatPeriod1 >= 3000) || 
                        ((thisHeartbeatPeriod < prevHeartbeatPeriod1 + heartbeatRange &&
                          thisHeartbeatPeriod > prevHeartbeatPeriod1 - heartbeatRange) &&
                         (thisHeartbeatPeriod < prevHeartbeatPeriod2 + heartbeatRange &&
                          thisHeartbeatPeriod > prevHeartbeatPeriod2 - heartbeatRange));

    static int irregularHeartbeatStreak = 0; // Debounce irregular pulses

    if ((periodsMatch && thisHeartbeatPeriod > 75) || justPlayedWinningTune > 0)
       {
        irregularHeartbeatStreak = 0; // Reset streak on valid pulse
        raspiOn = 1;
        if(justPlayedWinningTune > 0) justPlayedWinningTune -= 1;
        if(firstTimePiOn)
        {
          timeSincePiConnected = 0; // This timer is used for where it "disconnects" within a few seconds of booting. 
          Serial.println("Pi connected!!");
          if (SDSuccess && WAVMode)  tmrpcm.play("PiCon.wav");
          firstTimePiOff = 1;
        }
        firstTimePiOn = 0;
       }
    else {
      irregularHeartbeatStreak++;
      // Require 3 consecutive irregular pulses before declaring disconnected (prevents false disconnects on single frame jitter)
      if(raspiOn == 1 && timeSincePiConnected > 7000 && irregularHeartbeatStreak >= 3)
      {
        // The pi is no longer processing frames 
        if(firstTimePiOff)
        {
          Serial.println("Pi disconnected from irregular pulses");
          if (SDSuccess && WAVMode)  tmrpcm.play("PiDis.wav");
        }
        firstTimePiOff = 0;
        raspiOn = 0;
      }
    }
    // Update our heartbeat history
    prevHeartbeatPeriod2 = prevHeartbeatPeriod1;
    prevHeartbeatPeriod1 = thisHeartbeatPeriod; 
    
    timeHeartbeat = 0; // reset timer
    prevHeartbeatValue = digitalRead(PiPinHeartbeat);
    if(digitalRead(PiPinHeartbeat)) // Indicator light for each frame processed
      leds[126] = CRGB::White;
    else leds[126] = CRGB::Black;
    FastLED.show();
  }

  // Brightness Slider
  if(analogBright.hasChanged())
      {
        //Change the brightness
        currentBright = analogBright.getValue();
        int tempBrightVal = 1023 - currentBright; // Reverse the order so right is brightest
        tempBrightVal = map(tempBrightVal, 0, 1023, 10, 255);
        FastLED.setBrightness(tempBrightVal);
        FastLED.show();
      }
  // Color Sliders
  if(analogHome.hasChanged())
      {
        // Change home color number
        currentHomeColor = analogHome.getValue();
        //Serial.println("Home color:  " + String(currentHomeColor));
        UpdateDisplay(); 
      }
  if(analogAway.hasChanged())
      {
        // Change home color number
        currentAwayColor = analogAway.getValue();
        //Serial.println("Away color:  " + String(currentAwayColor));
        UpdateDisplay(); 
      }

  int buttonsPressed = int(!digitalRead(HomeUpPin)) + int(!digitalRead(HomeDownPin)) + 
                       int(!digitalRead(AwayUpPin)) + int(!digitalRead(AwayDownPin));
   if(buttonsPressed >=2)
   {
    // delay a bit to give you time to press the last buttons
    delay(400);
    buttonsPressed = int(!digitalRead(HomeUpPin)) + int(!digitalRead(HomeDownPin)) + 
                       int(!digitalRead(AwayUpPin)) + int(!digitalRead(AwayDownPin));
   }
   
  // Change sport mode by pressing all 4 buttons simultaneously
  if(buttonsPressed == 4)
  {
    sportMode = sportMode + 1;
    if(sportMode > 1) sportMode = 0;

    awayScore = 0;
    homeScore = 0;
    timeManualScoreChange = 0; // Reset timer
    noteEvent("MD");
    UpdateDisplay();
    // 0 = Volleyball Mode
    if(sportMode == 0) {
      if (SDSuccess && WAVMode) tmrpcm.play("VBMode.wav");
      else tone(SpeakerOutPin, 100, 100);
    }
    // 1 = Tennis Mode
    else if (sportMode == 1)
    {
      // say "Tennis mode"
      if (SDSuccess && WAVMode) tmrpcm.play("TMode.wav");
      else {tone(SpeakerOutPin, 100, 100); delay(100); tone(SpeakerOutPin, 100, 100); }
    }
    // 2 = Ultimate Frisbee
    else{
      if (SDSuccess && WAVMode) tmrpcm.play("UMode.wav");
      else {tone(SpeakerOutPin, 100, 100); delay(100); 
            tone(SpeakerOutPin, 100, 100); delay(100); 
            tone(SpeakerOutPin, 100, 100); }
    }
    Serial.println("Sport mode changed");
    sendStateIfDue(true);

    // wait for buttons to be released 
    while(buttonsPressed >= 3){
      delay(5);
      buttonsPressed = int(!digitalRead(HomeUpPin)) + int(!digitalRead(HomeDownPin)) + 
                       int(!digitalRead(AwayUpPin)) + int(!digitalRead(AwayDownPin));
    }
    

  }

  // Change WAV/Tone mode by pressing any 3 buttons simultaneously
  
  else if(buttonsPressed == 3)
  {
    if(WAVMode >= 1) WAVMode = 0;
    else WAVMode = 1;
    noteEvent("SM");
    sendStateIfDue(true);
    // Don't have to change scores since reset button will have reset it to 0:0

    if (SDSuccess && WAVMode)
      {
      tmrpcm.play("WavMd.wav"); // say "Speech Mode" or similar
      delay(1752);
      }
    else {
      for (int i = 50; i < 350; i+=10)
        {tone(SpeakerOutPin, i, 10);
        delay(9);}
    }
    Serial.println("Sound Mode Changed");
    // wait for buttons to be released 
    while(buttonsPressed >= 3){
      delay(5);
      buttonsPressed = int(!digitalRead(HomeUpPin)) + int(!digitalRead(HomeDownPin)) + 
                       int(!digitalRead(AwayUpPin)) + int(!digitalRead(AwayDownPin));
    }
  }

  // 2 buttons pressed in volleyball mode to change between game to 21, 25, and 15 
  else if(buttonsPressed == 2)
  {
    timeManualScoreChange = 0; // Reset timer
    UpdateDisplay(); 
    // 0 = Volleyball Mode scores 21 --> 25 --> 15 --> 21 etc
    if(sportMode == 0) {
      if (volleyballScoreTo == 21)
      {
        volleyballScoreTo = 25;
        if (SDSuccess && WAVMode) tmrpcm.play("VBto25.wav");
        else tone(SpeakerOutPin, 100, 100);
      }
      else if (volleyballScoreTo == 25)
      {
        volleyballScoreTo = 15;
        if (SDSuccess && WAVMode) tmrpcm.play("VBto15.wav");
        else tone(SpeakerOutPin, 100, 100);
      }
      else if (volleyballScoreTo == 15)
      {
        volleyballScoreTo = 21;
        if (SDSuccess && WAVMode) tmrpcm.play("VBto21.wav");
        else tone(SpeakerOutPin, 100, 100);
      } 
      Serial.println("Volleyball game to score changed");
      noteEvent("GT");
      sendStateIfDue(true);
    }
    while(buttonsPressed >= 2){
      delay(5);
      buttonsPressed = int(!digitalRead(HomeUpPin)) + int(!digitalRead(HomeDownPin)) +
                       int(!digitalRead(AwayUpPin)) + int(!digitalRead(AwayDownPin));
    }
  }

  sendStateIfDue(false);
}


















// Update the display with new numbers and colors etc. 
void UpdateDisplay()
{

  // Extract the digits
  int homeDigitLeft = homeScore / 10;
  int homeDigitRight = homeScore % 10;
  int awayDigitLeft = awayScore / 10;
  int awayDigitRight = awayScore % 10;

  // Update the LCD
  if (LCDUpdate > LCDRefreshRate)
  {
    lcd.clear();
    lcd.setCursor(0,0); //Column, Row
    lcd.print("Home: " + String(int(homeScore)));
    lcd.setCursor(0,1); 
    lcd.print("Away: " + String(int(awayScore)));
    if (sportMode == 1)
    { lcd.setCursor(9,0); //Column, Row
      lcd.print("Tennis");
    }
    else{
      lcd.setCursor(9,0); //Column, Row
      lcd.print("V-ball");
    }
    LCDUpdate = 0; //reset timer
  }
  

 // Account for the mode
 if(sportMode == 1)  // TENNIS - NEEDS THOROUGH TESTING
 {


   //0, 15, 30 for score of 0,1,2
   if(homeScore == 1){ homeDigitLeft = 1; homeDigitRight = 5; }
   else if(homeScore == 2){ homeDigitLeft = 3; homeDigitRight = 0; }
   else if(homeScore == 3){ homeDigitLeft = 4; homeDigitRight = 0; }
   if(awayScore == 1){ awayDigitLeft = 1; awayDigitRight = 5; }
   else if(awayScore == 2){ awayDigitLeft = 3; awayDigitRight = 0; }
   else if(awayScore == 3){ awayDigitLeft = 4; awayDigitRight = 0; }


   //Deuces
   if( (abs(homeScore - awayScore) < 2)  && //Scores are within 1 of each other (40-40, ad-in, or ad-out)
      (homeScore >= 3 && awayScore >= 3)) //Both have at least 40 
   {
     Serial.println("Deuces");
     if(homeScore > awayScore ) // Advantage home
     { 
       homeDigitLeft  = 10; //10 = A
       homeDigitRight = 11; //11 = d
       awayDigitLeft  = 0;
       awayDigitRight = 12; //12 = -
     }
     else if(awayScore > homeScore) // Advantage away
     { 
       awayDigitLeft  = 10; //10 = A
       awayDigitRight = 11; //11 = d
       homeDigitLeft  = 0;
       homeDigitRight = 12; //12 = -
     }
     else if (homeScore == awayScore && homeScore > 3) // back to deuces past 40-40
     { 
       homeDigitLeft  = 11; //11 = d
       homeDigitRight = 13; //13 = E
       awayDigitLeft  = 14; //14 = U
       awayDigitRight = 15; //15 = c
     }
   }

   // Someone won!
   if (abs(homeScore - awayScore) >= 2 && (homeScore >=4 || awayScore >= 4)) 
   {
     Serial.println("Someone won");
     if(homeScore == 4 && awayScore <= 2) //45 to 0/15/30 for Home
     {
       homeDigitLeft = 4;
       homeDigitRight = 5;
     }
     else if(awayScore == 4 && homeScore <= 2) //45 to 0/15/30 for Away
     {
       awayDigitLeft = 4;
       awayDigitRight = 5;
     }
     //It was after deuces
     else
     {
      // Not sure what to display... Maybe add 5 for each deuce, so if you win after 2 deuces it will be 50-60
      Serial.println("Won after deuces");
      if (homeScore >= 4){
      homeDigitLeft  = (40 + (homeScore - 3) * 5) / 10;
      homeDigitRight = (40 + (homeScore - 3) * 5) % 10; }
      if(awayScore >= 4){
      awayDigitLeft  = (40 + (awayScore - 3) * 5) / 10;
      awayDigitRight = (40 + (awayScore - 3) * 5) % 10; }
     }
   }
 }

  int homeHue = map(currentHomeColor, 0, 1023, 0, 255);
  int awayHue = map(currentAwayColor, 0, 1023, 0, 255);

  // Remember exactly what is drawn, for the state line to the Pi (-1 = blank leading digit)
  shownDigits[0] = (homeScore >= 10 || homeDigitLeft > 0) ? homeDigitLeft : -1;
  shownDigits[1] = homeDigitRight;
  shownDigits[2] = (awayScore >= 10 || awayDigitLeft > 0) ? awayDigitLeft : -1;
  shownDigits[3] = awayDigitRight;

  // Home digit left
  for(int i = 0; i <= 6; i++)
  {
    for(int thisPixel = 0; thisPixel < 9; thisPixel++)
    {
      bool thisSegment = digitTable[homeDigitLeft][i];
      if(thisSegment && (homeScore >= 10 || homeDigitLeft > 0))
        { // Turn on these LEDs
          if(homeHue < HUE_WHITE_BELOW)
            leds[i * 9 + thisPixel] = CRGB::White;
          else if (homeHue > HUE_RAINBOW_ABOVE)
            leds[i * 9 + thisPixel] = CHSV(map(i*9+thisPixel,0,63,0,255), 255, 255);
          else
            leds[i * 9 + thisPixel] = CHSV(homeHue, 255, 255);
        }
      else
      { // Turn off this segment
        leds[i * 9 + thisPixel] = CRGB::Black;
      }
    }
  }
  // Home digit right
  for(int i = 0; i <= 6; i++)
  {
    for(int thisPixel = 0; thisPixel < 9; thisPixel++)
    {
      bool thisSegment = digitTable[homeDigitRight][i];
      if(thisSegment)
        { // Turn on these LEDs
          if(homeHue < HUE_WHITE_BELOW)
            leds[i * 9 + thisPixel + 63] = CRGB::White;
          else if (homeHue > HUE_RAINBOW_ABOVE)
            leds[i * 9 + thisPixel + 63] = CHSV(map(i*9+thisPixel,0,63,0,255), 255, 255);
          else
            leds[i * 9 + thisPixel + 63] = CHSV(homeHue, 255, 255);
        }
      else
      { // Turn off this segment
        leds[i * 9 + thisPixel + 63] = CRGB::Black;
      }
    }
  }

  // Away digit left
  for(int i = 0; i <= 6; i++)
  {
    for(int thisPixel = 0; thisPixel < 9; thisPixel++)
    {
      bool thisSegment = digitTable[awayDigitLeft][i];
      if(thisSegment && (awayScore >= 10 || awayDigitLeft > 0))
        { // Turn on these LEDs
          if(awayHue < HUE_WHITE_BELOW)
            leds[i * 9 + thisPixel + 126] = CRGB::White;
          else if (awayHue > HUE_RAINBOW_ABOVE)
            leds[i * 9 + thisPixel + 126] = CHSV(map(i*9+thisPixel,0,63,0,255), 255, 255);
          else
            leds[i * 9 + thisPixel + 126] = CHSV(awayHue, 255, 255);
        }
      else
      { // Turn off this segment
        leds[i * 9 + thisPixel + 126] = CRGB::Black;
      }
    }
  }
  // Away digit right
  for(int i = 0; i <= 6; i++)
  {
    for(int thisPixel = 0; thisPixel < 9; thisPixel++)
    {
      bool thisSegment = digitTable[awayDigitRight][i];
      if(thisSegment)
        { // Turn on these LEDs
          if(awayHue < HUE_WHITE_BELOW)
            leds[i * 9 + thisPixel + 189] = CRGB::White;
          else if (awayHue > HUE_RAINBOW_ABOVE)
            leds[i * 9 + thisPixel + 189] = CHSV(map(i*9+thisPixel,0,63,0,255), 255, 255);
          else
            leds[i * 9 + thisPixel + 189] = CHSV(awayHue, 255, 255);
        }
      else
      { // Turn off this segment
        leds[i * 9 + thisPixel + 189] = CRGB::Black;
      }
    }
  }
  
  FastLED.show();

  // Game won song
  int winScore = volleyballScoreTo; //21 or 25 for volleyball.  7 for my ultimate group.  
  
  if(sportMode == 1) // Tennis
  {winScore = 4;}
  if(sportMode == 2) {winScore = 7;} // Ultimate Frisbee

  if (((homeScore >= winScore && (homeScore - awayScore >= 2)) ||
       (awayScore >= winScore && (awayScore - homeScore >= 2))) &&
        gameWonFirstTime)
    {
//      delay(600);
      if (SDSuccess && WAVMode){while(tmrpcm.isPlaying()) delay(1);}
      Serial.println("SOMEONE WON!!!");
      justPlayedWinningTune = 5;
      // Play a celebration noise
      gameWonFirstTime = 0;
      noteEvent(homeScore > awayScore ? "HW" : "AW");
      sendStateIfDue(true); // the song below blocks the loop for several seconds
      if(homeScore > awayScore) {
        if (SDSuccess && WAVMode) tmrpcm.play("Champ.wav"); // We are the champions
        else playRickRoll();
        }
      else  //https://bleacherreport.com/articles/1458324-the-20-most-famous-songs-in-sports //https://www.musicgrotto.com/pump-up-songs/
      {  if (SDSuccess && WAVMode)  tmrpcm.play("allWin.wav");
        else playGameOfThrones();
      }
      if (SDSuccess && WAVMode){
        while(tmrpcm.isPlaying()) 
        {
          delay(1);
          if(digitalRead(PiPinHeartbeat) != prevHeartbeatValue)
            {
              long thisHeartbeatPeriod = (long)timeHeartbeat;
              prevHeartbeatPeriod2 = prevHeartbeatPeriod1;
              prevHeartbeatPeriod1 = thisHeartbeatPeriod; 
              timeHeartbeat = 0; // reset timer
              prevHeartbeatValue = digitalRead(PiPinHeartbeat);
            }
        }
      }
    }

  
  
//  Serial.print("Home: " + String(homeScore));
//  Serial.print("\tAway: " + String(awayScore));
  
//  Serial.print("H+:" + String(digitalRead(HomeUpPin)));
//  Serial.print("\tH-:" + String(digitalRead(HomeDownPin)));
//  Serial.print("\tH_:" + String(analogRead(HomeSliderPin)));
//  Serial.print("\tA+:" + String(digitalRead(AwayUpPin)));
//  Serial.print("\tA-:" + String(digitalRead(AwayDownPin)));
//  Serial.print("\tA_:" + String(analogRead(AwaySliderPin)));
//  Serial.print("Reset:" + String(digitalRead(ResetPin)));
//  Serial.print("\tBright:" + String(analogRead(BrightSliderPin)));

//  Serial.println("");
//  delay(100);
}

// Turns the outside lights to blue 
void makeBorderBlue()
{
  int borderLights[60] = { 0,  2,  4,  6,  8,  9,  11,   13,   15,   17,   18,   20,   22,   24,   26,   54,   56,   58,   60,   62,   81,   83,   85,   87,   89,   117,  119,  121,  123,  125,  144,  146,  148,  150,  152,  180,  182,  184,  186,  188,  207,  209,  211,  213,  215,  243,  245,  247,  249,  251,  216,  218,  220,  222,  224,  234,  236,  238,  240,  242};
 for (int i = 0; i < 60; i++)
  {
    leds[borderLights[i]] = CRGB::Blue;         
  }
  FastLED.show();
}

// Record what caused the latest change, for the phone ("T-pose, home!")
void noteEvent(const char* code)
{
  lastEvent = code;
  eventSeq++;
}

int colorCode(int hue)
{
  if(hue < HUE_WHITE_BELOW) return COLOR_WHITE;
  if(hue > HUE_RAINBOW_ABOVE) return COLOR_RAINBOW;
  return hue;
}

// Send the state line to the Pi when something changed (at most every 100ms) or once a second.
// force: send now (if the TX buffer has room), e.g. right before a blocking song or button-release wait.
void sendStateIfDue(bool force)
{
  if(!force && timeSinceStateSent < 100) return;

  char body[64];
  int n = snprintf(body, sizeof(body), "S,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%s,%d",
                   homeScore, awayScore, sportMode, volleyballScoreTo, (int)raspiOn,
                   colorCode(map(currentHomeColor, 0, 1023, 0, 255)),
                   colorCode(map(currentAwayColor, 0, 1023, 0, 255)),
                   shownDigits[0], shownDigits[1], shownDigits[2], shownDigits[3],
                   lastEvent, (int)eventSeq);
  if(n <= 0 || n >= (int)sizeof(body)) return;
  if(!force && timeSinceStateSent < 1000 && strcmp(body, lastStateBody) == 0) return; // nothing new

  // Never block the scoreboard on the Pi: write only if the whole line fits in the TX buffer
  if(Serial1.availableForWrite() < n + 6) return;

  byte checksum = 0;
  for(int i = 0; i < n; i++) checksum ^= body[i];
  char tail[8];
  snprintf(tail, sizeof(tail), "*%02X\r\n", checksum);
  Serial1.write('$');
  Serial1.write(body, n);
  Serial1.write(tail);

  strcpy(lastStateBody, body);
  timeSinceStateSent = 0;
}

void playASong(int melodyArray[], int tempo)
{
  int buzzer = SpeakerOutPin;
  int notes = sizeof(melodyArray) / sizeof(melodyArray[0]) / 2;
  int wholenote = (60000 * 4) / tempo;
  int divider = 0, noteDuration = 0;

  for (int thisNote = 0; thisNote < notes * 2; thisNote = thisNote + 2) {
    divider = melodyArray[thisNote + 1];
    if (divider > 0) {
      noteDuration = (wholenote) / divider;
    } else if (divider < 0) {
      noteDuration = (wholenote) / abs(divider);
      noteDuration *= 1.5; // increases the duration in half for dotted notes
    }
    tone(buzzer, melodyArray[thisNote], noteDuration * 0.9);
    delay(noteDuration);
    noTone(buzzer);

    if(digitalRead(PiPinHeartbeat) != prevHeartbeatValue)
    {
      long thisHeartbeatPeriod = (long)timeHeartbeat;
      prevHeartbeatPeriod2 = prevHeartbeatPeriod1;
      prevHeartbeatPeriod1 = thisHeartbeatPeriod; 
      timeHeartbeat = 0; // reset timer
      prevHeartbeatValue = digitalRead(PiPinHeartbeat);
    }
  }
}


void playRickRoll()
{
  int tempo = 200; // default was 114
  int buzzer = SpeakerOutPin;
  int notes = sizeof(melodyRickRoll) / sizeof(melodyRickRoll[0]) / 2;
  int wholenote = (60000 * 4) / tempo;
  int divider = 0, noteDuration = 0;

  for (int thisNote = 0; thisNote < notes * 2; thisNote = thisNote + 2) {
    divider = melodyRickRoll[thisNote + 1];
    if (divider > 0) {
      noteDuration = (wholenote) / divider;
    } else if (divider < 0) {
      noteDuration = (wholenote) / abs(divider);
      noteDuration *= 1.5; // increases the duration in half for dotted notes
    }
    tone(buzzer, melodyRickRoll[thisNote], noteDuration * 0.9);
    delay(noteDuration);
    noTone(buzzer);

    if(digitalRead(PiPinHeartbeat) != prevHeartbeatValue)
    {
      long thisHeartbeatPeriod = (long)timeHeartbeat;
      prevHeartbeatPeriod2 = prevHeartbeatPeriod1;
      prevHeartbeatPeriod1 = thisHeartbeatPeriod; 
      timeHeartbeat = 0; // reset timer
      prevHeartbeatValue = digitalRead(PiPinHeartbeat);
    }
  }
}

void playGameOfThrones()
{
  int tempo = 125; // default was 83
  int buzzer = SpeakerOutPin;
  int notes = sizeof(melodyGameOfThrones) / sizeof(melodyGameOfThrones[0]) / 2;
  int wholenote = (60000 * 4) / tempo;
  int divider = 0, noteDuration = 0;

  for (int thisNote = 0; thisNote < notes * 2; thisNote = thisNote + 2) {
    divider = melodyGameOfThrones[thisNote + 1];
    if (divider > 0) {
      noteDuration = (wholenote) / divider;
    } else if (divider < 0) {
      noteDuration = (wholenote) / abs(divider);
      noteDuration *= 1.5; // increases the duration in half for dotted notes
    }
    tone(buzzer, melodyGameOfThrones[thisNote], noteDuration * 0.9);
    delay(noteDuration);
    noTone(buzzer);

    if(digitalRead(PiPinHeartbeat) != prevHeartbeatValue)
    {
      long thisHeartbeatPeriod = (long)timeHeartbeat;
      prevHeartbeatPeriod2 = prevHeartbeatPeriod1;
      prevHeartbeatPeriod1 = thisHeartbeatPeriod; 
      timeHeartbeat = 0; // reset timer
      prevHeartbeatValue = digitalRead(PiPinHeartbeat);
    }
  }
}
