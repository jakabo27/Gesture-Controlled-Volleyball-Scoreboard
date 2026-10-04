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
#define BRIDGED_AUDIO 0
#define BEEP_PITCH 1      // multiplier for the beep pitches (voice mode off / no SD card). 1 = the original low
                          // tones (preferred); higher values are louder on a small speaker.   // 1 = also output inverted audio on pin 2 (for a differential amp input), see setup()

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
bool SDSuccess = true;
int sportMode = 0; // 0 = Volleyball.  1 = Tennis.  2 = ??
bool WAVMode = true; // true = play .wav files if SD card works.  False = beeps only (follows soundMode)
// Sound mode (3-button chord or the phone): 0 = sound effects (default), 1 = the voice says "Point home" / "Point away"
// on + presses (PtHm.wav / PtAwy.wav), 2 = generated tones only. 0 and 1 use WAV files; 2 never touches the SD card.
int soundMode = 0;
int volleyballScoreTo = 21; //15, 21, or 25, defaulting to 21

// Color slider ends: below HUE_WHITE_BELOW the digits are white, above HUE_RAINBOW_ABOVE they are a rainbow
#define HUE_WHITE_BELOW 10
#define HUE_RAINBOW_ABOVE 240

// State broadcast to the Raspberry Pi on Serial3 (TX3 = pin 14), one way: the Pi forwards it to the phone.
// The Arduino never waits on the Pi: a line is only written when the TX buffer has room for all of it,
// otherwise it is skipped and sent on a later loop. One line per change (at most every 100ms) and at
// least once a second:
//   $S,<home>,<away>,<sportMode>,<scoreTo>,<piOn>,<homeColor>,<awayColor>,<d0>,<d1>,<d2>,<d3>,<event>,<eventSeq>*<XOR>\r\n
// Colors: 0-255 = FastLED hue, 256 = white, 257 = rainbow. d0-d3 = digitTable index of the home tens,
// home ones, away tens and away ones digits as drawn (-1 = blank). XOR = hex XOR of the chars between $ and *.
#define PI_LINK_BAUD 38400
// Debug output on USB serial (115200): "[LINK] ..." lines for the state broadcast and Pi commands. Set to 0 to silence.
// Lines are only printed when the USB TX buffer has room, so debugging can never stall the scoreboard.
#define LINK_DEBUG 1
unsigned long linkTxLines = 0, linkTxSkipped = 0, linkRxBytes = 0, linkRxGood = 0, linkRxBad = 0;
elapsedMillis timeSinceLinkStats;
#define COLOR_WHITE 256
#define COLOR_RAINBOW 257
elapsedMillis timeSinceStateSent;
int shownDigits[4] = {-1, 0, -1, 0};
const char* lastEvent = "BOOT"; // HU/HD/AU/AD buttons, HP/AP Pi point, HC/AC cobra, RS reset, HW/AW won, MD sport mode, GT game-to, SM sound mode
byte eventSeq = 0;
char lastStateBody[64] = "";

// Button chords: press 2, 3 or 4 score buttons together. A single press acts immediately; if more buttons
// join, it was the start of a chord and is undone. The chord fires on press (all 4 down, or no new button for
// CHORD_SETTLE_MS) and then every score button is ignored until all are released, so letting go can never
// trigger anything.
#define CHORD_SETTLE_MS 350
#define CHORD_UNDO_MS 1500      // a single press this recent is undone when it turns into a chord
int prevButtonsHeld = 0;
int chordButtons = 0;           // most score buttons held at once in the chord being formed
bool chordLatched = false;      // chord done: wait for every score button to be released
elapsedMillis chordSettle;
elapsedMillis timeSincePress = 10000;
int pressHome = 0, pressAway = 0;   // score before the latest fresh press (for the undo)
bool pressGameWon = true;

// Celebration song, non-blocking so any button press can cut it off
const char* pendingSongWav = NULL;  // waits for the point sound to finish, then starts
bool songWavPlaying = false;
const int* melodyNotes = NULL;      // tone() fallback when there is no SD card / voice mode is off
int melodyPairs = 0;
int melodyPos = 0;
long melodyWholeNote = 0;
unsigned long melodyNoteMs = 0;
elapsedMillis melodyTimer;

// Commands from the Pi on Serial3 RX (phone settings): "$C,<name>,<value>*<XOR>"
char cmdBuf[32];
byte cmdLen = 0;
bool cmdActive = false;

//LCD 
LCD_I2C lcd(0x27); 
elapsedMillis LCDUpdate;
int LCDRefreshRate = delayManualChange - 10; //ms between updating LCD



void makeBorderBlue();
void UpdateDisplay();
void startCelebration(bool homeWon);
void stopCelebration();
bool celebrationActive();
void serviceAudio();
void serviceSerialCommands();
int scoreButtonsHeld();
void runChord(int buttons);
void setSportMode(int mode);
void setScoreTo(int to);
void toggleSoundMode();
void setSoundMode(int mode);
void noteEvent(const char* code);
void beep(unsigned int freq, unsigned long ms);
void releaseSpeakerPin();
void sendStateIfDue(bool force);
void homeUp();
void homeDown();
void awayUp();
void awayDown();

void setup() {
  
  Serial.begin(115200);
  Serial3.begin(PI_LINK_BAUD); // state broadcast to the Pi (see sendStateIfDue)

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
  tmrpcm.quality(1); // 2x oversampling: 32 kHz PWM carrier (inaudible) with a 500-step range at 16 kHz WAVs
  // Volume = sample shift: setVolume(4) = x1, setVolume(5) = x2. Samples are 8-bit (0-255), so x2 spans 0-510:
  // a full-scale clip fills the whole 500-step PWM range. 5 is the loudest setting that doesn't clip, as long
  // as the WAVs are normalized (tools/clean_wavs.py peaks them at 120/127). 6 (x4) would clip.
  tmrpcm.setVolume(5);  
  pinMode(SpeakerOutPin, OUTPUT);
#if BRIDGED_AUDIO
  // TMRpcm already drives an inverted copy of the audio on OC3B (Mega pin 2). With an amplifier that has a
  // differential input, wire IN+ to pin 5 and IN- to pin 2: twice the voltage swing (+6 dB) at the same clip point.
  pinMode(2, OUTPUT);
#endif
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

  // Score buttons. 2, 3 or 4 pressed together are a chord (see runChord); otherwise each acts on its own.
  int buttonsHeld = scoreButtonsHeld();
  if(buttonsHeld > 0 && prevButtonsHeld == 0)
  { // fresh press: remember the score, in case this press turns out to be the start of a chord
    pressHome = homeScore;
    pressAway = awayScore;
    pressGameWon = gameWonFirstTime;
    timeSincePress = 0;
  }
  prevButtonsHeld = buttonsHeld;

  if(chordLatched)
  {
    if(buttonsHeld == 0) chordLatched = false; // every button released: back to normal
  }
  else if(buttonsHeld >= 2)
  {
    if(buttonsHeld > chordButtons) { chordButtons = buttonsHeld; chordSettle = 0; }
    if(chordButtons == 4 || chordSettle >= CHORD_SETTLE_MS)
    {
      // The first button of the chord already counted as a point: undo it
      if(timeSincePress < CHORD_UNDO_MS && (homeScore != pressHome || awayScore != pressAway))
      {
        homeScore = pressHome;
        awayScore = pressAway;
        gameWonFirstTime = pressGameWon;
        stopCelebration();
        UpdateDisplay();
      }
      runChord(chordButtons);
      chordLatched = true;
      chordButtons = 0;
    }
  }
  else
  {
  chordButtons = 0;
  // Home Up
  if(!digitalRead(HomeUpPin) && timeManualScoreChange > delayManualChange) homeUp();
  // Home Down
  if(!digitalRead(HomeDownPin) && timeManualScoreChange > delayManualChange) homeDown();
  // Away Up
  if(!digitalRead(AwayUpPin) && timeManualScoreChange > delayManualChange) awayUp();
  // Away Down
  if(!digitalRead(AwayDownPin) && timeManualScoreChange > delayManualChange) awayDown();
  } // end single-button handling

  // Reset
  if(!digitalRead(ResetPin) && timeManualScoreChange > delayManualChange)
  {
    stopCelebration();
    awayScore = 0; 
    homeScore = 0;
    gameWonFirstTime = 1;
    timeManualScoreChange = 0; // Reset timer
    noteEvent("RS");
    UpdateDisplay(); 
    if (SDSuccess && WAVMode )
      tmrpcm.play("Reset.wav");
    else 
      beep(50, 65);
  }
  
  // Home Up from Pi
  if(digitalRead(PiPinHome) && timePiChange > delayPiChange && raspiOn)
  {
    homeScore = homeScore + 1; // increase score
    timePiChange = 0; // Reset timer
    noteEvent("HP");
    if(!celebrationActive())
    {
      if (SDSuccess && WAVMode)
        tmrpcm.play("PtHm.wav");
      else 
        beep(400, 200);
    }
    UpdateDisplay(); 
    Serial.println("Point Home");
  }
  // Away Up from Pi
  if(digitalRead(PiPinAway) && timePiChange > delayPiChange && raspiOn)
  {
    awayScore = awayScore + 1; // increase score
    timePiChange = 0; // Reset timer
    noteEvent("AP");
    if(!celebrationActive())
    {
      if (SDSuccess && WAVMode)
        tmrpcm.play("PtAwy.wav");
      else 
        beep(500, 200);
    }
    Serial.println("Point away");
    UpdateDisplay(); 
  }

  //Surrender Cobra Home from Pi (Home down)
  if(digitalRead(PiPinSurrenderHome) && timePiChange > delayPiChange && raspiOn)
  {
    stopCelebration();
    homeScore = homeScore - 1; // decrease score
    if(homeScore < 0) homeScore = 0;
    timePiChange = 0; // Reset timer
    noteEvent("HC");
    UpdateDisplay(); 
    if (SDSuccess && WAVMode)
      tmrpcm.play("SurHo.wav");
    else 
      beep(400, 300);
    Serial.println("Surrender Cobra Home");
  }
  // Surrender Cobra Away from Pi (Away Down)
  if(digitalRead(PiPinSurrenderAway) && timePiChange > delayPiChange && raspiOn)
  {
    stopCelebration();
    awayScore = awayScore - 1; // decrease score
    if(awayScore < 0) awayScore = 0;
    timePiChange = 0; // Reset timer
    noteEvent("AC");
    UpdateDisplay(); 
    if (SDSuccess && WAVMode)
      tmrpcm.play("SurAw.wav");
    else 
      beep(500, 300);
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
    
    // Fixed by Antigravity: lowered threshold from 300ms to 75ms to support high-speed Pi execution (up to 13 FPS)
    // Also allow instant connection on boot if previous periods are still in initial uncalibrated state (>= 3000ms)
    bool periodsMatch = (prevHeartbeatPeriod1 >= 3000) || 
                        ((thisHeartbeatPeriod < prevHeartbeatPeriod1 + heartbeatRange &&
                          thisHeartbeatPeriod > prevHeartbeatPeriod1 - heartbeatRange) &&
                         (thisHeartbeatPeriod < prevHeartbeatPeriod2 + heartbeatRange &&
                          thisHeartbeatPeriod > prevHeartbeatPeriod2 - heartbeatRange));

    static int irregularHeartbeatStreak = 0; // Debounce irregular pulses

    if (periodsMatch && thisHeartbeatPeriod > 75)
       {
        irregularHeartbeatStreak = 0; // Reset streak on valid pulse
        raspiOn = 1;
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

  serviceAudio();           // celebration song / melody, non-blocking
  serviceSerialCommands();  // phone settings from the Pi
  sendStateIfDue(false);
}


















// ---- Score changes: the same code runs for the physical buttons and the phone (SCORE command) --------
void homeUp()
{
  stopCelebration(); // any button press cuts the celebration song short
  homeScore = homeScore + 1; // increase score
  timeManualScoreChange = 0; // Reset timer
  noteEvent("HU");

    if (SDSuccess && WAVMode){
      if(soundMode == 1)      tmrpcm.play("PtHm.wav");   // "Point home"
      else if(homeScore%3==0) tmrpcm.play("hUp1.wav");
      else if(homeScore%3==1) tmrpcm.play("hUp2.wav");
      else if(homeScore%3==2) tmrpcm.play("hUp3.wav");}
    else
      beep(100, 100);
  UpdateDisplay();
  Serial.println("Home up");
}

void homeDown()
{
  stopCelebration();
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
    beep(100, 50);
  Serial.println("Home down");
}

void awayUp()
{
  stopCelebration();
  awayScore = awayScore + 1; // increase score
  timeManualScoreChange = 0; // Reset timer
  noteEvent("AU");

    if (SDSuccess && WAVMode){
      if(soundMode == 1)      tmrpcm.play("PtAwy.wav");  // "Point away"
      else if(awayScore%3==0) tmrpcm.play("aUp1.wav");
      else if(awayScore%3==1) tmrpcm.play("aUp2.wav");
      else if (awayScore%3==2) tmrpcm.play("aUp3.wav");}
    else
      beep(350, 100);
  UpdateDisplay();
  Serial.println("Away up");
}

void awayDown()
{
  stopCelebration();
  awayScore = awayScore - 1; // decrease score
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
    beep(75, 65);
  Serial.println("Away down");
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
      Serial.println("SOMEONE WON!!!");
      gameWonFirstTime = 0;
      noteEvent(homeScore > awayScore ? "HW" : "AW");
      // Non-blocking: starts after the point sound finishes, and any button press cuts it off
      startCelebration(homeScore > awayScore);
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
  int n = snprintf(body, sizeof(body), "S,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%s,%d,%d",
                   homeScore, awayScore, sportMode, volleyballScoreTo, (int)raspiOn,
                   colorCode(map(currentHomeColor, 0, 1023, 0, 255)),
                   colorCode(map(currentAwayColor, 0, 1023, 0, 255)),
                   shownDigits[0], shownDigits[1], shownDigits[2], shownDigits[3],
                   lastEvent, (int)eventSeq, soundMode);
  if(n <= 0 || n >= (int)sizeof(body)) return;
  if(!force && timeSinceStateSent < 1000 && strcmp(body, lastStateBody) == 0) return; // nothing new

  // Never block the scoreboard on the Pi: write only if the whole line fits in the TX buffer
  if(Serial3.availableForWrite() < n + 6) { linkTxSkipped++; return; }

  byte checksum = 0;
  for(int i = 0; i < n; i++) checksum ^= body[i];
  char tail[8];
  snprintf(tail, sizeof(tail), "*%02X\r\n", checksum);
  Serial3.write('$');
  Serial3.write(body, n);
  Serial3.write(tail);

  strcpy(lastStateBody, body);
  timeSinceStateSent = 0;
  linkTxLines++;
#if LINK_DEBUG
  if(Serial.availableForWrite() > n + 24)
  {
    Serial.print("[LINK] TX $"); Serial.print(body); Serial.print("*"); Serial.println(checksum, HEX);
  }
#endif
}

// ---- Celebration song (non-blocking) ---------------------------------------------------------------
void startMelody(const int* notes, int pairs, int tempo)
{
  melodyNotes = notes;
  melodyPairs = pairs;
  melodyPos = 0;
  melodyWholeNote = (60000L * 4) / tempo;
  melodyNoteMs = 0;
  melodyTimer = 0;
}

void startCelebration(bool homeWon)
{
  if(SDSuccess && WAVMode)
    pendingSongWav = homeWon ? "Champ.wav" : "allWin.wav";   // starts once the point sound has finished
  else if(homeWon)
    startMelody(melodyRickRoll, sizeof(melodyRickRoll) / sizeof(melodyRickRoll[0]) / 2, 200);
  else
    startMelody(melodyGameOfThrones, sizeof(melodyGameOfThrones) / sizeof(melodyGameOfThrones[0]) / 2, 125);
}

bool celebrationActive()
{
  return pendingSongWav != NULL || songWavPlaying || melodyNotes != NULL;
}

void stopCelebration()
{
  pendingSongWav = NULL;
  if(songWavPlaying) { tmrpcm.stopPlayback(); songWavPlaying = false; }
  if(melodyNotes) { noTone(SpeakerOutPin); melodyNotes = NULL; }
}

// Called every loop: starts a queued song, and plays the next melody note when the last one is done
void serviceAudio()
{
  if(songWavPlaying && !tmrpcm.isPlaying()) songWavPlaying = false;
  if(pendingSongWav && !tmrpcm.isPlaying())
  {
    tmrpcm.play(pendingSongWav);
    pendingSongWav = NULL;
    songWavPlaying = true;
  }
  if(melodyNotes && melodyTimer >= melodyNoteMs)
  {
    if(melodyPos >= melodyPairs) { noTone(SpeakerOutPin); melodyNotes = NULL; return; }
    int note = melodyNotes[melodyPos * 2];
    int divider = melodyNotes[melodyPos * 2 + 1];
    long duration = divider > 0 ? melodyWholeNote / divider : (melodyWholeNote / abs(divider)) * 3 / 2; // negative = dotted
    if(note == REST) noTone(SpeakerOutPin);
    else { releaseSpeakerPin(); tone(SpeakerOutPin, note, duration * 9 / 10); } // melody: real pitch
    melodyNoteMs = duration;
    melodyTimer = 0;
    melodyPos++;
  }
}

// tone() toggles pin 5 directly, but after a WAV has played TMRpcm's Timer3 still owns that pin (its PWM output
// stays connected when a file ends), so every beep came out faint or silent. Disconnect it first; the next
// tmrpcm.play() reconnects it (timerSt() rewrites TCCR3A).
void releaseSpeakerPin()
{
  if (tmrpcm.isPlaying()) tmrpcm.stopPlayback();
  TCCR3A &= ~(_BV(COM3A1) | _BV(COM3A0) | _BV(COM3B1) | _BV(COM3B0));
}

void beep(unsigned int freq, unsigned long ms)
{
  releaseSpeakerPin();
  tone(SpeakerOutPin, freq * BEEP_PITCH, ms);
}

// ---- Button chords and settings ------------------------------------------------------------------
int scoreButtonsHeld()
{
  return int(!digitalRead(HomeUpPin)) + int(!digitalRead(HomeDownPin)) +
         int(!digitalRead(AwayUpPin)) + int(!digitalRead(AwayDownPin));
}

// Any 2 buttons: volleyball game-to 21 -> 25 -> 15. Any 3: voice / beeps. All 4: volleyball <-> tennis.
void runChord(int buttons)
{
  timeManualScoreChange = 0;
  if(buttons >= 4) setSportMode(sportMode == 0 ? 1 : 0);
  else if(buttons == 3) toggleSoundMode();
  else if(sportMode == 0) setScoreTo(volleyballScoreTo == 21 ? 25 : (volleyballScoreTo == 25 ? 15 : 21));
  else beep(60, 150); // tennis has no game-to setting
}

void setScoreTo(int to)
{
  volleyballScoreTo = to;
  stopCelebration();
  if (SDSuccess && WAVMode) tmrpcm.play(to == 25 ? "VBto25.wav" : (to == 15 ? "VBto15.wav" : "VBto21.wav"));
  else beep(100, 100);
  Serial.println("Volleyball game to score changed");
  noteEvent("GT");
  sendStateIfDue(true);
}

void setSportMode(int mode)
{
  sportMode = mode;
  homeScore = 0;
  awayScore = 0;
  gameWonFirstTime = 1; // new game: the winner's song can play again
  stopCelebration();
  noteEvent("MD");
  UpdateDisplay();
  if (SDSuccess && WAVMode) tmrpcm.play(sportMode == 0 ? "VBMode.wav" : "TMode.wav");
  else beep(sportMode == 0 ? 100 : 200, 150);
  Serial.println("Sport mode changed");
  sendStateIfDue(true);
}

// 3-button chord: effects -> "Point home/away" voice -> tones -> effects ...
void toggleSoundMode()
{
  setSoundMode((soundMode + 1) % 3);
}

void setSoundMode(int mode)
{
  if(mode < 0 || mode > 2) return;
  soundMode = mode;
  WAVMode = (soundMode != 2);
  stopCelebration();
  noteEvent("SM");
  if (SDSuccess && soundMode == 0)
    tmrpcm.play("WavMd.wav");      // the announcement for the default sound effects
  else if (SDSuccess && soundMode == 1)
    tmrpcm.play("PtHm.wav");       // demo of the new sound: "Point home"
  else
  {
    for (int i = 50; i < 350; i += 10) { beep(i, 10); delay(9); } // ~0.3 s rising sweep
  }
  Serial.print("Sound mode: "); Serial.println(soundMode);
  sendStateIfDue(true);
}

// ---- Commands from the Pi (phone settings) ---------------------------------------------------------
// "$C,MODE,<0|1>*<XOR>" sport mode (resets the score, like the 4-button chord)
// "$C,TO,<15|21|25>*<XOR>" volleyball game-to
// XOR = hex XOR of the characters between $ and *. Anything malformed is ignored.
void linkLog(const char* what, const char* line)
{
#if LINK_DEBUG
  if(Serial.availableForWrite() > (int)(strlen(what) + strlen(line) + 14)) { Serial.print("[LINK] RX "); Serial.print(what); Serial.print(": "); Serial.println(line); }
#endif
}

void handleCommand(char* line)
{
  char raw[sizeof(cmdBuf)];
  strncpy(raw, line, sizeof(raw) - 1); raw[sizeof(raw) - 1] = 0;
  char* star = strrchr(line, '*');
  if(!star || strlen(star + 1) != 2) { linkRxBad++; linkLog("no checksum", raw); return; }
  *star = 0;
  byte checksum = 0;
  for(char* p = line; *p; p++) checksum ^= *p;
  if(strtol(star + 1, NULL, 16) != checksum) { linkRxBad++; linkLog("bad checksum", raw); return; }
  if(strncmp(line, "C,", 2) != 0) { linkRxBad++; linkLog("not a command", raw); return; }
  char* name = line + 2;
  char* comma = strchr(name, ',');
  if(!comma) { linkRxBad++; linkLog("malformed", raw); return; }
  *comma = 0;
  const char* arg = comma + 1;
  int value = atoi(arg);

  if(strcmp(name, "SCORE") == 0)
  {
    // Phone +/- buttons: run the same code as the physical buttons (with a shorter 250ms rate limit)
    bool ok = true;
    if(timeManualScoreChange <= 250) { linkLog("SCORE too soon", raw); return; }   // taps closer than 250ms apart are ignored
    if(strcmp(arg, "HU") == 0) homeUp();
    else if(strcmp(arg, "HD") == 0) homeDown();
    else if(strcmp(arg, "AU") == 0) awayUp();
    else if(strcmp(arg, "AD") == 0) awayDown();
    else ok = false;
    if(ok) { linkRxGood++; linkLog("SCORE accepted", raw); }
    else { linkRxBad++; linkLog("unknown SCORE", raw); }
    return;
  }
  if(strcmp(name, "SOUND") == 0 && value >= 0 && value <= 2)
  {
    linkRxGood++; linkLog("SOUND accepted", raw);
    if(value != soundMode) setSoundMode(value);
  }
  else if(strcmp(name, "MODE") == 0 && (value == 0 || value == 1))
  {
    linkRxGood++; linkLog("MODE accepted", raw);
    if(value != sportMode) setSportMode(value);
  }
  else if(strcmp(name, "TO") == 0 && (value == 15 || value == 21 || value == 25))
  {
    linkRxGood++; linkLog("TO accepted", raw);
    if(value != volleyballScoreTo) setScoreTo(value);
  }
  else { linkRxBad++; linkLog("unknown command", raw); }
}

void serviceSerialCommands()
{
  while(Serial3.available())
  {
    char c = Serial3.read();
    linkRxBytes++;
    if(c == '$') { cmdActive = true; cmdLen = 0; }
    else if(!cmdActive) continue;
    else if(c == '\r' || c == '\n') { cmdBuf[cmdLen] = 0; cmdActive = false; handleCommand(cmdBuf); }
    else if(cmdLen < sizeof(cmdBuf) - 1) cmdBuf[cmdLen++] = c;
    else cmdActive = false; // too long: not ours
  }
#if LINK_DEBUG
  if(timeSinceLinkStats > 5000)   // ~6 ms of USB serial every 5 s (may briefly wait for buffer space)
  {
    timeSinceLinkStats = 0;
    Serial.print("[LINK] stats tx="); Serial.print(linkTxLines);
    Serial.print(" txSkipped="); Serial.print(linkTxSkipped);
    Serial.print(" rxBytes="); Serial.print(linkRxBytes);
    Serial.print(" cmdOk="); Serial.print(linkRxGood);
    Serial.print(" cmdBad="); Serial.println(linkRxBad);
  }
#endif
}
