# TheEntireWorld
Downloadable Tools for DCC and Content Creation Pipelines; Starting with Animation and Cinematic Exporter for Maya and Motionbuilder with imports into Unreal 5.5, adding Human IK Builder for maya in the most recent version

Instructions for first time using:

1. inside of tools, there will be a .bat file for the version of Maya you use (2023 - 2025 officially tests) or the version of Motionbuilder you use (2023 - 2026 officially working). It is recommended to run the first time as this will make sure you have the requests module... you may also opt to run maya_setup.py directly or motionbuilder_setup.py respectively
   
2. After that point you should be able to open maya or motionbuilder vanilla without the bat file, and the tool should open up and prompt you to select a Uproject, which once you select will update your unreal to be able to be sent commands from Maya and Motionbuilder.
   
3. I walk through the functionality of our Animation Manager (with exports for Unreal Sequencer) and how to get this setup in a few vimeo videos, though some updates have happened since then to the UI and the setup... this part is defined there : https://vimeo.com/user58067839 ; https://vimeo.com/user58067839 . This tool also handles Metahuman on top of any base rigs you have for your project (must have skeleton in engine to define in DCC )

4. Beyond that once you have the UI open, the videos above show how to use the interface and I will be adding a paper documentation shortly

5. The only thing we ask is that if you do use our tools in your production, that you credit our studio for your tooling support, to help get our name out there. Honor system, please don't abuse the help we provide without helping us in return :)

6. I've recently added a Human IK Character Builder, which t poses the rig and does some autodetection for joint names as well: https://vimeo.com/1087030142

#To Launch tool

Using the bat files, you should have a menu in maya and motionbuilder on startup titled "The Entire World Tools" with a Sequence UI item in the menu... but if you prefer to run manually or on your own shelf:

#Sequence UI
from maya_tools.Cinematics.SequenceUI import sequence_ui
sequence_ui.show_animation_manager()

#Human IK UI
from maya_tools.Rigging.mocap import hik_ui
hik_ui.launch_hik_ui()


To test the Sequence UI, I have included Mannequin rigs I found online so the skeleton to test will already be included in your project once you open it up.
The rigs were found here, i recommend supporting them if you care to donate on their page: https://gumroad.com/d/27fecce80492ca58d194844412cc370b

They exist in /ArtSource/Rigs inside The download from GitHub, I will be adding more to this as I go
