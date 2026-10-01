import copy
import os
import time
from datetime import datetime
import argparse
import cv2 as cv
import numpy as np
import tflite_runtime.interpreter as tflite
from digitalio import DigitalInOut, Direction, Pull
import board
from imutils.video import VideoStream
from imutils.video import FPS
import logging

# My files in the same directory as this one
from myImageFunctions import draw_debug
from myDisplayFunctions import displayOLED, clearDisplay

# # Pin number (not like "GPIO number" like Pin#) - These aren't used any more.  
# homeScorePinNum = 31
# awayScorePinNum = 29
# sparePinNum = 33
# powerOffButtonNum = 32
# heartbeatPinNum = 37
# surrenderHomePinNum = 35 # Orange skinny wire
# surrenderAwayPinNum = 40 # Yellow skinny wire

logging.basicConfig(filename='/home/pi/Documents/LoggingMain.log', filemode='a',level=logging.DEBUG)

homeScorePin = DigitalInOut(board.D6)
awayScorePin = DigitalInOut(board.D5)
sparePin = DigitalInOut(board.D13)
heartbeatPin = DigitalInOut(board.D26)
powerOffButtonPin = DigitalInOut(board.D12)
surrenderHomePin = DigitalInOut(board.D19)
surrenderAwayPin = DigitalInOut(board.D21)

homeScorePin.direction = Direction.OUTPUT
awayScorePin.direction = Direction.OUTPUT
sparePin.direction = Direction.OUTPUT
heartbeatPin.direction = Direction.OUTPUT
powerOffButtonPin.direction = Direction.INPUT
powerOffButtonPin.pull = Pull.UP
surrenderHomePin.direction = Direction.OUTPUT
surrenderAwayPin.direction = Direction.OUTPUT

homeScorePin.value = 0
awayScorePin.value = 0
sparePin.value = 0
heartbeatPin.value = 0
cv.destroyAllWindows()
surrenderHomePin.value = 0
surrenderAwayPin.value = 0


def run_inference(interpreter, input_size, image):
    #startReshape = time.time()
    image_width, image_height = image.shape[1], image.shape[0]

    # Pre process:Resize, BGR->RGB, Reshape, float32 cast
    input_image = cv.resize(image, dsize=(input_size[1], input_size[0]), interpolation= cv.INTER_LINEAR)
    input_image = cv.cvtColor(input_image, cv.COLOR_BGR2RGB)
    input_image = input_image.reshape(-1, input_size[0], input_size[1], 3)
    input_image = input_image.astype('float32')
    #input_image = tf.cast(input_image, dtype=tf.float32)
    #print("Reshaping took {:.3f} ms".format((time.time() - startReshape)*1000))
    
    # Inference
    #inferenceStart = time.time()
    input_details = interpreter.get_input_details()
    interpreter.set_tensor(input_details[0]['index'], input_image)
    interpreter.invoke()

    output_details = interpreter.get_output_details()
    raw_output = interpreter.get_tensor(output_details[0]['index'])
    
    # Ensure 2D shape (N, 56) regardless of whether N=0, N=1, or N>6
    if raw_output.ndim == 3:
        keypoints_with_scores = raw_output[0]
    elif raw_output.ndim == 2:
        keypoints_with_scores = raw_output
    elif raw_output.ndim == 1:
        keypoints_with_scores = np.expand_dims(raw_output, axis=0)
    else:
        keypoints_with_scores = np.empty((0, 56))

    # If more than 6 people are detected, sort by confidence score (index 55) and keep top 6
    if len(keypoints_with_scores) > 6:
        keypoints_with_scores = sorted(
            keypoints_with_scores, 
            key=lambda p: p[55] if len(p) > 55 else 0.0, 
            reverse=True
        )[:6]

    # Postprocess: Calc Keypoint, bounding box
    keypoints_list, scores_list = [], []
    bbox_list = []
    for keypoints_with_score in keypoints_with_scores:
        if len(keypoints_with_score) < 56:
            continue
            
        keypoints = []
        scores = []
        # keypoints
        for index in range(17):
            idx_y = index * 3 + 0
            idx_x = index * 3 + 1
            idx_s = index * 3 + 2
            kp_y = np.clip(keypoints_with_score[idx_y], 0.0, 1.0)
            kp_x = np.clip(keypoints_with_score[idx_x], 0.0, 1.0)
            score = float(keypoints_with_score[idx_s])
            
            keypoint_x = int(image_width  * kp_x)
            keypoint_y = int(image_height * kp_y)
            keypoints.append([keypoint_x, keypoint_y])
            scores.append(score)
        
        # bounding box: clamp to image boundaries to prevent crashes
        b_ymin = np.clip(keypoints_with_score[51], 0.0, 1.0)
        b_xmin = np.clip(keypoints_with_score[52], 0.0, 1.0)
        b_ymax = np.clip(keypoints_with_score[53], 0.0, 1.0)
        b_xmax = np.clip(keypoints_with_score[54], 0.0, 1.0)
        bbox_ymin = int(image_height * b_ymin)
        bbox_xmin = int(image_width  * b_xmin)
        bbox_ymax = int(image_height * b_ymax)
        bbox_xmax = int(image_width  * b_xmax)
        bbox_score = float(keypoints_with_score[55])
        
        keypoints_list.append(keypoints)
        scores_list.append(scores)
        bbox_list.append([bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax, bbox_score])

    return keypoints_list, scores_list, bbox_list


def EndAndShutDown():
    vs.stop()
    clearDisplay()
    cv.destroyAllWindows()
    sparePin.value = 0
    heartbeatPin.value = 0
    os.system("shutdown now -h")
    
    
# Use a specific model from:
#   192,192   192,256   256,256    256,320    320,320
dimY = 256
dimX = 256
modelPath = '/home/pi/Documents/resources/saved_model_' + str(dimY) + 'x' + str(dimX) + '/model_float16_quant.tflite'
#modelPath = '/home/pi/Documents/resources/MultiTemp/model_weight_quant.tflite'
resultPath = '/home/pi/Documents/Syncme/'
input_size = [dimY,dimX]

# Load model
interpreter = tflite.Interpreter(model_path=modelPath, num_threads=3)
interpreter.allocate_tensors()

TPoseCounterLeft  = 0 # Count consecutive t-poses
TPoseCounterRight = 0
TPoseCounter = 0
powerButtonCounter = 0
heartbeatValue = 0

# Initialize video capture
# IMutils documentation at https://github.com/PyImageSearch/imutils/blob/master/imutils/video/videostream.py
vs = VideoStream().start()
# Change resolution by editing /home/pi/.local/lib/python3.7/site-packages/imutils/video/webcamvideostream.py
# if you mess up settings again, run v4l2-ctl -l to see the defaults, then
# set with v4l2-ctl -d /dev/video1 -c exposure_auto=1  for example. 

start_time = time.time()
lastButtonPressTime = time.time() # Keep track of when pushbutton last pressed in
lastRandomFrameSavedTime = time.time() # When saved a non-tPose image
lastTPoseSavedTime = time.time()

saveResult    = False    # save an image when t-pose detected
usePopup      = False   # Use the popup display to show the webcam
useRGBDisplay = True    # Use the RGB OLED display to show frames
drawImage = saveResult or usePopup or useRGBDisplay # basically always true when using the OLED display

keypoint_score_th = 0.18
bbox_score_th = 0.27
threshSlope = 0.65  # Arms - first week was 0.8, second 0.9
legThreshold =  3 # legs - first week was 2.5



while True:
    
    # Capture read
    frame = vs.read()
    if frame is None:
        print("Source ended, looping until source restarts")
        logging.info("CAMERA SOURCE ENDED!! Check overheating camera")
        while frame is None:
            frame = vs.read()
            time.sleep(0.01)
        
    try:
        # Remove top and bottom 20% ish    
        frame = frame[int(frame.shape[0] * 0.1):int(frame.shape[0]*0.85),:]
        debug_image = frame
        
        # Save the original frame every 45 seconds to start building a test dataset
        if time.time() > (lastRandomFrameSavedTime + 30):
            resultName = resultPath + "NoTpose/Random "+datetime.now().strftime("%b-%d %H.%M.%S") + ".jpg"
            cv.imwrite(resultName, frame)
            lastRandomFrameSavedTime = time.time()

        # Split the image into left and right halves
        width_cutoff = frame.shape[1] // 2
        leftHalf = frame[:, :width_cutoff]
        rightHalf = frame[:, width_cutoff:]
    except:
       print("Exception in initial frame processing - removing top and bottom, splitting in half")
       logging.exception('')
       
    # Inference execution
    # Left side
    keypoints_list, scores_list, bbox_list = run_inference(interpreter, input_size, leftHalf,)
    debug_image, thisLeftTpose, thisLeftSurrender= draw_debug(debug_image,
        keypoints_list, scores_list, bbox_list, drawImage=drawImage,
        threshSlope=threshSlope, legThreshold=legThreshold)
    if thisLeftTpose or thisLeftSurrender:
        try:
            # Run it again on this side if we detected a T-Pose
            tempFrame = vs.read()  # Take a new pic from the webcam
            tempFrame = tempFrame[int(tempFrame.shape[0] * 0.1):int(tempFrame.shape[0]*0.8),:] # Crop out top and bottom
            tempFrame = tempFrame[:, :width_cutoff] # Left Half only
            tempDebugImage = debug_image
            
            keypoints_list, scores_list, bbox_list = run_inference(interpreter, input_size, tempFrame,)
            tempDebugImage, thisLeftTpose, thisLeftSurrender= draw_debug(tempDebugImage,
                keypoints_list, scores_list, bbox_list, drawImage=drawImage,
                threshSlope=threshSlope, legThreshold=legThreshold)
            
            del tempFrame, tempDebugImage # Delete the variables - probably doesn't matter but whatever
        except:
            print("Exception verifying a T-Pose left side")
            logging.exception('')
    
    # Right side
    if not thisLeftTpose:
        keypoints_list, scores_list, bbox_list = run_inference(interpreter, input_size, rightHalf,)
        debug_image, thisRightTpose, thisRightSurrender = draw_debug(debug_image,
            keypoints_list, scores_list, bbox_list, drawOffset=width_cutoff, drawImage=drawImage,
            threshSlope=threshSlope, legThreshold=legThreshold)
        if thisRightTpose or thisRightSurrender:
            try:
                # Run it again on this side if we detected a T-Pose
                tempFrame = vs.read()  # Take a new pic from the webcam
                tempFrame = tempFrame[int(tempFrame.shape[0] * 0.1):int(tempFrame.shape[0]*0.8),:] # Crop out top and bottom
                tempFrame = tempFrame[:, width_cutoff:] # Right Half only
                tempDebugImage = debug_image
                
                keypoints_list, scores_list, bbox_list = run_inference(interpreter, input_size, tempFrame,)
                tempDebugImage, thisRightTpose, thisRightSurrender= draw_debug(tempDebugImage,
                    keypoints_list, scores_list, bbox_list, drawOffset=width_cutoff, drawImage=drawImage,
                    threshSlope=threshSlope, legThreshold=legThreshold)
                
                del tempFrame, tempDebugImage # Delete the variables - probably doesn't matter but whatever
            except:
                print("Exception verifying a T-pose right side")
                logging.exception('')
    
    elapsed_time = time.time() - start_time
    start_time = time.time()
    print("Processed frame in {:.2f} seconds".format(elapsed_time))
    
    # Update counters for consecutive poses
    if thisLeftTpose:
        TPoseCounterLeft += 1
        print("Found a t-pose Home!")
        #sparePin.value = 1
    else:
        TPoseCounterLeft = 0
    if thisRightTpose:
        TPoseCounterRight += 1
        print("Found a t-pose Away!")
        #sparePin.value = 1
    else:
        TPoseCounterRight = 0
        
    if not (thisLeftTpose or thisRightTpose):
        sparePin.value = 0
    try:
        if(thisLeftTpose):
            print("Home T-Pose!")
            homeScorePin.value = 1
            time.sleep(0.05)
            homeScorePin.value = 0
            TPoseCounterLeft = 0
            TPoseCounterRight = 0
            if (saveResult and (time.time() - lastTPoseSavedTime > 3)):
                # Save image with debug drawings
                resultName = resultPath + datetime.now().strftime("%b-%d %H.%M.%S") + " Home.jpg"
                cv.imwrite(resultName, debug_image)
                # Save original image without any drawings over it
                resultName = resultPath + "TposeNoDebug/" +datetime.now().strftime("%b-%d %H.%M.%S") + " Home.jpg"
                cv.imwrite(resultName, frame)
                lastTPoseSavedTime = time.time()
    except:
        print("Exception with confirmed left t-pose when changing pins or saving image")
        logging.exception('')
    try:
        if(thisRightTpose):
            print("Away T-Pose!")
            awayScorePin.value = 1
            time.sleep(0.05)
            awayScorePin.value = 0
            TPoseCounterRight = 0
            TPoseCounterLeft = 0
            if (saveResult and (time.time() - lastTPoseSavedTime > 3)):
                resultName = resultPath + datetime.now().strftime("%b-%d %H.%M.%S") + " Away.jpg"
                cv.imwrite(resultName, debug_image)
                resultName = resultPath + "TposeNoDebug/" +datetime.now().strftime("%b-%d %H.%M.%S") + " Away.jpg"
                cv.imwrite(resultName, frame)
                lastTPoseSavedTime = time.time()
    except:
        print("Exception with confirmed right t-pose when changing pins or saving image")
        logging.exception('')

    if(thisLeftSurrender):
        print("SURRENDER HOME!!")
        surrenderHomePin.value = 1
        time.sleep(0.05)
        surrenderHomePin.value = 0
        
    if(thisRightSurrender):
        print("SURRENDER AWAY!!")
        surrenderAwayPin.value = 1
        time.sleep(0.05)
        surrenderAwayPin.value = 0
    
    heartbeatPin.value = heartbeatValue
    heartbeatValue = not heartbeatValue
    
    try:
        # Check for using the button to shut down the Pi or display images
        powerButton = powerOffButtonPin.value
        if(not powerButton):
            powerButtonCounter += 1
            print(powerButtonCounter)
            lastButtonPressTime = time.time()
        else:
            powerButtonCounter = 0
        if(powerButtonCounter >= 10):
            print("Shutting down the system!")
            EndAndShutDown()
        
        if usePopup:
            cv.imshow('Pose Detection', debug_image)
            key = cv.waitKey(1)
            if key == 27:  # ESC
                break
        
        timeSinceButtonPressed = time.time() - lastButtonPressTime 
        if useRGBDisplay and timeSinceButtonPressed < 20:
            displayOLED(cv.cvtColor(debug_image, cv.COLOR_BGR2RGB),
                        elapsedTime=elapsed_time,
                        powerButton=powerButtonCounter,
                        leftT=thisLeftTpose, rightT=thisRightTpose)
        if (21 < timeSinceButtonPressed < 23):
            clearDisplay() # Blank the screen after 15 seconds
    except:
        print("Exception with closing commands")
        logging.exception('')
        
cv.destroyAllWindows()
sparePin.value = 0
vs.stop()
clearDisplay()



