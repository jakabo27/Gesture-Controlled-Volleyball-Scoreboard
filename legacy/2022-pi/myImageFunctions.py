import copy
import cv2 as cv
from datetime import datetime
from math import sqrt, acos, degrees
import logging
logging.basicConfig(filename='/home/pi/Documents/LoggingImageFunctionsFile.log', filemode='a',level=logging.DEBUG)

colors = [[0,100,255], [0,100,255], [0,255,255], [0,100,255], [0,255,255],
    [0,100,255], [0,255,0], [255,200,100], [255,0,255], [0,255,0],
    [255,200,100], [255,0,255], [0,0,255], [255,0,0], [200,200,0],
    [255,0,0], [200,200,0], [0,0,0]]
POSE_PAIRS = [[0,1], [0,2], [1,3], [2,4], [0,5], [0,6], [5,6], 
                [5,7], [7,9], [6,8], [8,10], [11,12], [5,11], [11,13],
                [13,15], [6,12], [12,14], [14,16]]
keypointsMapping = ['Nose', 'L-Eye', 'R-Eye', 'L-Ear', 'R-Ear', 'L-Sho',
                    'R-Sho', 'L-Elb', 'R-Elb', 'L-Wr', 'R-Wr', 'L-Hip',
                    'R-Hip', 'L-Knee', 'R-Knee', 'L-Ank', 'R-ank']
connect_list = [
    [0, 1, (255, 0, 0)],  # nose → left eye
    [0, 2, (0, 0, 255)],  # nose → right eye
    [1, 3, (255, 0, 0)],  # left eye → left ear
    [2, 4, (0, 0, 255)],  # right eye → right ear
    [0, 5, (255, 0, 0)],  # nose → left shoulder
    [0, 6, (0, 0, 255)],  # nose → right shoulder
    [5, 6, (100, 255, 0)],  # left shoulder → right shoulder
    [5, 7, (255, 100, 0)],  # left shoulder → left elbow
    [7, 9, (255, 100, 0)],  # left elbow → left wrist
    [6, 8, (0, 100, 255)],  # right shoulder → right elbow
    [8, 10, (50, 100, 255)],  # right elbow → right wrist
    [11, 12, (0, 255, 0)],  # left hip → right hip
    [5, 11, (255, 0, 0)],  # left shoulder → left hip
    [11, 13, (255, 0, 0)],  # left hip → left knee
    [13, 15, (255, 0, 0)],  # left knee → left ankle
    [6, 12, (0, 0, 255)],  # right shoulder → right hip
    [12, 14, (0, 0, 255)],  # right hip → right knee
    [14, 16, (0, 0, 255)],  # right knee → right ankle
]

myArmList =  [
    [5, 6, (100, 255, 0), 0],  # left shoulder → right shoulder
    [8, 10,(50, 100, 255),1],  # right elbow → right wrist
    [6, 8, (0, 100, 255), 2],  # right shoulder → right elbow
    [5, 7, (255, 255, 0), 3],  # left shoulder → left elbow
    [7, 9, (255, 100, 0), 4],  # left elbow → left wrist
    [14, 12, (0, 0, 255), 5],  # right hip to right knee
    [13, 11, (255, 0, 0), 6],  # left hip to left knee
    
]


def draw_debug(image,keypoints_list,scores_list,
    bbox_list, drawOffset=0, thisTPoseCounter=0, keypoint_score_th=0.3,
               bbox_score_th=0.3, drawImage=False,
               threshSlope=0.8, legThreshold=2.5):
    debug_image = copy.deepcopy(image)

    # grab the middle section slope
    centerSlope = 100
    tpose = False
    surrenderCobra = False
    mySlopes = [100,200,400,500,500,1,1]
    myPointsA = [0,0,0,0,0,0,0,0]
    myPointsB = [0,0,0,0,0,0,0,0]
    thisBox = 0
    
    idx = 0
    for keypoints, scores, bbox in zip(keypoints_list, scores_list, bbox_list):
        mySlopes = [100,200,400,500,500,1,1]
        myPointsA = [0,0,0,0,0,0,0,0]
        myPointsB = [0,0,0,0,0,0,0,0]
        try:
            # Connect Lines 
            if drawImage:
                for (index01, index02, color, idx) in myArmList:
                    if scores[index01] > keypoint_score_th and scores[
                            index02] > keypoint_score_th:
                        point01 = [keypoints[index01][0]+drawOffset, keypoints[index01][1]]
                        point02 = [keypoints[index02][0]+drawOffset, keypoints[index02][1]]
                        cv.line(debug_image, point01, point02, color, 2)
        except:
            print("Exception drawing on image in first part of myImageFunctions.py")
            logging.exception('')
        try:
            
            # T-Pose stuff
            myPointsAllFound = 1
            for (index01, index02, color, idx) in myArmList:
                if not( scores[5] > keypoint_score_th and scores[6] > keypoint_score_th and
                scores[7] > keypoint_score_th  and scores[8]  > keypoint_score_th and
                scores[9] > keypoint_score_th  and scores[10] > keypoint_score_th and
                scores[11] > keypoint_score_th and scores[12] > keypoint_score_th and
                scores[13] > keypoint_score_th and scores[14] > keypoint_score_th):
                    myPointsAllFound = 0
                    break
                    
                point01 = keypoints[index01]
                point02 = keypoints[index02]
                myPointsA[idx] = point01
                myPointsB[idx] = point02
                
                try:
                    # Slope calculation
                    if point02[1] == point01[1]:
                        thisSlope = 0    # Horizontal
                    elif (point02[0] == point01[0]):
                        thisSlope = 1000 # Vertical
                    else:
                        thisSlope = (point02[1] - point01[1]) / (point02[0] - point01[0]) * -1
                    mySlopes[idx] = thisSlope
                except:
                    print("Exception calculating slopes")
                    logging.exception("Exception calculating slopes")   

                if index01 == 5 and index02 == 6:
                    centerSlope = thisSlope
                    #print('Center Slope:   {:.3f}'.format(centerSlope))
                    # print("Center slope: {:.3f}".format(centerSlope))
                #elif index01 < 14:
                    #result = thisSlope < centerSlope + threshSlope and thisSlope > centerSlope - threshSlope
                    # print("{:.0f} to \t{:.0f}: {:.3f} \t Result: {:b}".format(index01, index02, thisSlope, result))

                # if drawImage:
                #     cv.putText(debug_image, "{:.3f}".format(thisSlope),
                #                (int((point01[0]+point02[0])/2)+5,int((point01[1]+point02[1])/2)), 
                #                cv.FONT_HERSHEY_TRIPLEX, 0.6, (255,255,255), 1)
                
                # Testing for the surrender cobra
                #print("{:2d},{:4d},{:4d},{:4d},{:4d},{:.5f}".format(idx,point01[0],point01[1],point02[0],point02[1],thisSlope),end=',')    
                #if idx == 6:
                #    print("\n")
            # Surrender Cobra calculations
            if myPointsAllFound:
                try:
                    Rlen1 = sqrt((myPointsB[1][1]-myPointsA[1][1])**2 + (myPointsB[1][0] - myPointsA[1][0])**2)
                    Rlen2 = sqrt((myPointsB[2][1]-myPointsA[2][1])**2 + (myPointsB[2][0] - myPointsA[2][0])**2)
                    Rlen3 = sqrt((myPointsB[1][1]-myPointsA[2][1])**2 + (myPointsB[1][0] - myPointsA[2][0])**2)
                    Rangle = 1
                    if Rlen1 > 1e-4 and Rlen2 > 1e-4:
                        cos_r = max(-1.0, min(1.0, (Rlen1**2 + Rlen2**2 - Rlen3**2) / (2 * Rlen1 * Rlen2)))
                        Rangle = degrees(acos(cos_r))
                    
                    Llen1 = sqrt((myPointsB[3][1]-myPointsA[3][1])**2 + (myPointsB[3][0] - myPointsA[3][0])**2)
                    Llen2 = sqrt((myPointsB[4][1]-myPointsA[4][1])**2 + (myPointsB[4][0] - myPointsA[4][0])**2)
                    Llen3 = sqrt((myPointsB[4][1]-myPointsA[3][1])**2 + (myPointsB[4][0] - myPointsA[3][0])**2)
                    Langle = 1
                    if Llen1 > 1e-4 and Llen2 > 1e-4:
                        cos_l = max(-1.0, min(1.0, (Llen1**2 + Llen2**2 - Llen3**2) / (2 * Llen1 * Llen2)))
                        Langle = degrees(acos(cos_l))
                    print("{:.2f} deg(L) \t {:.2f} deg(R). \tCenter:{:.2f} \tSlope1: {:.2f}, \tSlope2: {:.2f} \tSlope3: {:.2f}, \tSlope4: {:.2f}\tB:{:.0f} A:{:.0f}".format(Rangle,
                                                                                                    Langle, centerSlope, mySlopes[1], mySlopes[2], mySlopes[3], mySlopes[4], myPointsB[4][1], (myPointsA[3][1] - 5)))
                    
                    if (myPointsAllFound and
                        Langle > 40 and Langle < 80 and
                        Rangle > 40 and Rangle < 80 and
                        myPointsB[4][1] < (myPointsA[3][1] - 5)     and # Left wrist is higher than left shoulder (y origin seems to be top left)
                        myPointsB[1][1] < (myPointsB[2][1] - 5)     and
                        centerSlope > -0.3   and centerSlope <  0.3 and # Must be fairly flat
                        mySlopes[1] >  0.1   and mySlopes[1] <  0.8 and 
                        mySlopes[2] > -1.4   and mySlopes[2] < -0.4 and
                        mySlopes[3] >  0.6   and mySlopes[3] <  1.5 and 
                        mySlopes[4] > -0.7   and mySlopes[4] <  0.0 
                        ):
                        surrenderCobra = True
                        #print("surrender")
                except:
                    print("Exception calculating surrender cobra")
                    logging.exception("Exception calculating surrender cobra") 
            # Decide if it's a T-pose or not
            
            if (myPointsAllFound and
               (mySlopes[1] < centerSlope + threshSlope and mySlopes[1] > centerSlope - threshSlope) and
               (mySlopes[2] < centerSlope + threshSlope and mySlopes[2] > centerSlope - threshSlope) and  # Arm parts are parallel ish to shoulder-shoulder line
               (mySlopes[3] < centerSlope + threshSlope and mySlopes[3] > centerSlope - threshSlope) and
               (mySlopes[4] < centerSlope + threshSlope and mySlopes[4] > centerSlope - threshSlope) and
               (myPointsA[1][0] < myPointsA[2][0] and myPointsA[2][0] < myPointsA[3][0] and myPointsA[3][0] < myPointsA[4][0]) # Arms straight out both sides
               and (abs(mySlopes[5]) > legThreshold and abs(mySlopes[6]) > legThreshold) and              # Thighs are fairly vertical
                abs(centerSlope) < 0.3 # You aren't too tilted sideways
              ):
                
                tpose = True
                cv.putText(debug_image, "T-POSE!", (10+drawOffset,40),
                    cv.FONT_HERSHEY_SIMPLEX, 1.5, (255,255,255), 2)
                cv.rectangle(debug_image, (bbox[0]+drawOffset, bbox[1]), 
                    (bbox[2]+drawOffset, bbox[3]), (255*tpose, 255, 0), 2)
                
                # Save a cropped image of just the t-pose
    #             paddingAmount = 15
    #             cropX1 = bbox_list[thisBox][0] + drawOffset - paddingAmount
    #             cropY1 = bbox_list[thisBox][1] - paddingAmount
    #             cropX2 = bbox_list[thisBox][2] + drawOffset + paddingAmount
    #             cropY2 = bbox_list[thisBox][3] + paddingAmount
    #             if cropX1 < 0:
    #                 cropX1 = 0
    #             if cropY1 < 0:
    #                 cropY1 = 0
    #             if cropX2 > image.shape[1]:
    #                 cropX2 = image.shape[1]
    #             if cropY2 > image.shape[0]:
    #                 cropY2 = image.shape[0]
    #             cropped_image = image[cropY1:cropY2, cropX1:cropX2]
    #             resultPath = '/home/pi/Documents/Syncme/'
    #             resultName = resultPath + "TposeCropped/ "+datetime.now().strftime("%b-%d %H.%M.%S") + "-" + str(thisBox) + ".jpg"
    #             cv.imwrite(resultName, cropped_image)
                #cv.imshow('Cropped T', cropped_image)
    #             print('Center Slope:   {:.3f}'.format(mySlopes[0]))
    #             print('L Wrist-elbow:  {:.3f}'.format(mySlopes[1]))
    #             print('L Elbow-Should: {:.3f}'.format(mySlopes[2]))
    #             print('R Should-Elb:   {:.3f}'.format(mySlopes[3]))
    #             print('R Elb-Wrist:    {:.3f}'.format(mySlopes[4]))
    #             print('L-Leg:   {:.3f}'.format(mySlopes[5]))
    #             print('R-Leg:    {:.3f}'.format(mySlopes[6]))
                
                
            thisBox += 1
        except:
            print("Exception in main processing of myImageFunctions.py")
            logging.exception('')
            
            #print("leg1: " + str(myPointsA[5]) + "," + str(myPointsB[5]))
            #print("leg2: " + str(myPointsA[6]) + "," + str(myPointsB[6]))
            # Print the slopes in the corner if it's a T-pose
            #cv.putText(debug_image, 'Center Slope:   {:.3f}'.format(mySlopes[0]), (5,45), cv.FONT_HERSHEY_TRIPLEX, 0.8,  (255,255,255), 2)
            #cv.putText(debug_image, 'L Wrist-elbow:  {:.3f}'.format(mySlopes[1]), (5,75), cv.FONT_HERSHEY_TRIPLEX, 0.8,  (255,255,255), 2)
            #cv.putText(debug_image, 'L Elbow-Should: {:.3f}'.format(mySlopes[2]), (5,105), cv.FONT_HERSHEY_TRIPLEX, 0.8, (255,255,255), 2)
            #cv.putText(debug_image, 'R Should-Elb:   {:.3f}'.format(mySlopes[3]), (5,135), cv.FONT_HERSHEY_TRIPLEX, 0.8, (255,255,255), 2)
            #cv.putText(debug_image, 'R Elb-Wrist:    {:.3f}'.format(mySlopes[4]), (5,165), cv.FONT_HERSHEY_TRIPLEX, 0.8, (255,255,255), 2)
            #cv.putText(debug_image, 'L-Leg:   {:.3f}'.format(mySlopes[5]),        (5,195), cv.FONT_HERSHEY_TRIPLEX, 0.8, (255,255,255), 2)
            #cv.putText(debug_image, 'R-Leg:    {:.3f}'.format(mySlopes[6]),       (5,225), cv.FONT_HERSHEY_TRIPLEX, 0.8, (255,255,255), 2)
    # bounding boxes
    # for idx, bbox in enumerate(bbox_list):
    #     if bbox[4] > bbox_score_th and drawImage:
    #         cv.rectangle(debug_image, (bbox[0]+drawOffset, bbox[1]), 
    #             (bbox[2]+drawOffset, bbox[3]), (0, 255, 0), 7)
            #cv.putText(debug_image, str(idx),(bbox[0]+7+drawOffset, bbox[1]+25), 
            #    cv.FONT_HERSHEY_SIMPLEX, 0.7, (180,180,0), 2)

    # Inference elapsed time or FPS
#     if elapsed_time > 0 and drawImage:
#         cv.putText(debug_image, "FPS : " + '{:.1f}'.format(1/elapsed_time),
#         (10, 20), cv.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv.LINE_AA)
    
    # T-Pose running count
    #if tpose:
    #    thisTPoseCounter += 1
    #cv.putText(debug_image, "{:.0f}".format(thisTPoseCounter),
    #                       (20 + drawOffset,300), cv.FONT_HERSHEY_TRIPLEX, 3, (255,255,255), 2)
    return debug_image, tpose, surrenderCobra
